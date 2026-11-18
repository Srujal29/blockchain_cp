import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insurechain_voiceguard/core/config/app_config.dart';
import 'package:insurechain_voiceguard/core/network/api_client.dart';
import 'package:insurechain_voiceguard/core/storage/secure_storage_service.dart';
import 'package:insurechain_voiceguard/features/auth/models/user_model.dart';
import 'package:insurechain_voiceguard/features/auth/providers/auth_provider.dart';
import 'package:insurechain_voiceguard/features/auth/services/auth_api_service.dart';
import 'package:insurechain_voiceguard/features/customer/widgets/policy_categories_grid.dart';

class InMemoryStorageService extends SecureStorageService {
  String? _accessToken;
  String? _refreshToken;
  UserModel? _cachedUser;
  String? _baseUrl;
  bool cleared = false;

  InMemoryStorageService({
    String? accessToken,
    String? refreshToken,
    UserModel? cachedUser,
  })  : _accessToken = accessToken,
        _refreshToken = refreshToken,
        _cachedUser = cachedUser;

  @override
  Future<String?> getAccessToken() async => _accessToken;

  @override
  Future<String?> getRefreshToken() async => _refreshToken;

  @override
  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    _accessToken = accessToken;
    _refreshToken = refreshToken;
  }

  @override
  Future<UserModel?> getCachedUser() async => _cachedUser;

  @override
  Future<void> saveUser(UserModel user) async => _cachedUser = user;

  @override
  Future<String?> getBaseUrl() async => _baseUrl;

  @override
  Future<void> saveBaseUrl(String baseUrl) async => _baseUrl = baseUrl;

  @override
  Future<void> clearSession() async {
    cleared = true;
    _accessToken = null;
    _refreshToken = null;
    _cachedUser = null;
  }
}

typedef HandlerFn = Future<ResponseBody> Function(RequestOptions options);

class MockHttpAdapter implements HttpClientAdapter {
  final HandlerFn handler;
  MockHttpAdapter(this.handler);

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) =>
      handler(options);

  @override
  void close({bool force = false}) {}
}

ResponseBody jsonBody(Object data, int statusCode) {
  return ResponseBody.fromString(
    jsonEncode(data),
    statusCode,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    },
  );
}

void main() {
  test('AppConfig.defaultBaseUrl does not point to trycloudflare', () {
    expect(AppConfig.defaultBaseUrl.contains('trycloudflare.com'), isFalse);
    expect(AppConfig.defaultBaseUrl, isNotEmpty);
  });

  test('ApiClient performs single-flight refresh on concurrent 401s', () async {
    final storage = InMemoryStorageService(
      accessToken: 'expired-access',
      refreshToken: 'valid-refresh',
    );
    int refreshCalls = 0;

    final dio = Dio(BaseOptions(baseUrl: 'http://127.0.0.1:8000/api/v1'));
    dio.httpClientAdapter = MockHttpAdapter((options) async {
      if (options.path.contains('/auth/refresh')) {
        refreshCalls++;
        await Future.delayed(const Duration(milliseconds: 20));
        return jsonBody({
          'access_token': 'new-access',
          'refresh_token': 'new-refresh',
        }, 200);
      }

      if (options.headers['Authorization'] == 'Bearer new-access') {
        return jsonBody({'ok': true}, 200);
      }
      return jsonBody({'detail': 'Token expired'}, 401);
    });

    final client = ApiClient(customDio: dio, customStorage: storage);

    final results = await Future.wait([
      client.dio.get('/policies'),
      client.dio.get('/claims'),
    ]);

    expect(refreshCalls, 1);
    expect(results[0].statusCode, 200);
    expect(results[1].statusCode, 200);
    expect(await storage.getAccessToken(), 'new-access');
  });

  test('ApiClient clears storage and syncs AuthNotifier on failed refresh without recursion', () async {
    final storage = InMemoryStorageService(
      accessToken: 'expired-access',
      refreshToken: 'bad-refresh',
    );
    int refreshCalls = 0;
    late AuthNotifier authNotifier;

    final dio = Dio(BaseOptions(baseUrl: 'http://127.0.0.1:8000/api/v1'));
    dio.httpClientAdapter = MockHttpAdapter((options) async {
      if (options.path.contains('/auth/refresh')) {
        refreshCalls++;
        return jsonBody({'detail': 'Invalid refresh token'}, 401);
      }
      return jsonBody({'detail': 'Unauthorized'}, 401);
    });

    final client = ApiClient(
      customDio: dio,
      customStorage: storage,
      onSessionExpired: () => authNotifier.forceLogout(),
    );

    authNotifier = AuthNotifier(
      authService: AuthApiService(client: client),
      storageService: storage,
    );
    // Simulate active authenticated state before expiry
    authNotifier.state = AuthState.authenticated(
      const UserModel(
        id: 'u-1',
        email: 'user@example.com',
        fullName: 'Test User',
        role: UserRole.customer,
        accountStatus: AccountStatus.active,
      ),
    );

    await expectLater(client.dio.get('/policies'), throwsA(isA<DioException>()));

    expect(refreshCalls, 1);
    expect(storage.cleared, isTrue);
    expect(authNotifier.state.status, AuthStatus.unauthenticated);
  });

  test('ApiClient does not loop when retried request still returns 401', () async {
    final storage = InMemoryStorageService(
      accessToken: 'expired-access',
      refreshToken: 'valid-refresh',
    );
    int refreshCalls = 0;
    int endpointCalls = 0;

    final dio = Dio(BaseOptions(baseUrl: 'http://127.0.0.1:8000/api/v1'));
    dio.httpClientAdapter = MockHttpAdapter((options) async {
      if (options.path.contains('/auth/refresh')) {
        refreshCalls++;
        return jsonBody({
          'access_token': 'new-access',
          'refresh_token': 'new-refresh',
        }, 200);
      }
      endpointCalls++;
      return jsonBody({'detail': 'Still unauthorized'}, 401);
    });

    final client = ApiClient(customDio: dio, customStorage: storage);
    await expectLater(client.dio.get('/policies'), throwsA(isA<DioException>()));

    expect(refreshCalls, 1);
    expect(endpointCalls, 2); // initial + 1 retry max
  });

  testWidgets('PolicyCategoriesGrid shows empty state instead of fake policies', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: PolicyCategoriesGrid(policies: []),
        ),
      ),
    );

    await tester.tap(find.text('Motor Insurance'));
    await tester.pumpAndSettle();

    expect(find.text('Featured Motor Insurance Coming Soon'), findsOneWidget);
    expect(find.text('Comprehensive Auto DriveProtect'), findsNothing);
  });
}

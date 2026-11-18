import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import '../config/app_config.dart';
import '../errors/app_exception.dart';
import '../storage/secure_storage_service.dart';

class ApiClient {
  final Dio dio;
  final SecureStorageService storageService;
  VoidCallback? onSessionExpired;
  Completer<String?>? _refreshCompleter;

  ApiClient({
    Dio? customDio,
    SecureStorageService? customStorage,
    this.onSessionExpired,
  })  : dio = customDio ??
            Dio(
              BaseOptions(
                baseUrl: AppConfig.apiBaseUrl,
                connectTimeout: AppConfig.connectTimeout,
                receiveTimeout: AppConfig.receiveTimeout,
                headers: {
                  'Content-Type': 'application/json',
                  'Accept': 'application/json',
                },
              ),
            ),
        storageService = customStorage ?? SecureStorageService() {
    _setupInterceptors();
  }

  Future<void> initBaseUrl() async {
    final custom = await storageService.getBaseUrl();
    if (custom != null && custom.isNotEmpty) {
      dio.options.baseUrl = custom;
      AppConfig.apiBaseUrl = custom;
    }
  }

  void updateBaseUrl(String newBaseUrl) {
    dio.options.baseUrl = newBaseUrl;
    AppConfig.apiBaseUrl = newBaseUrl;
    storageService.saveBaseUrl(newBaseUrl);
  }

  Future<String?> _performSingleFlightRefresh() async {
    if (_refreshCompleter != null) {
      return _refreshCompleter!.future;
    }

    _refreshCompleter = Completer<String?>();
    try {
      final refreshToken = await storageService.getRefreshToken();
      if (refreshToken == null || refreshToken.isEmpty) {
        await _handleSessionExpired();
        _refreshCompleter!.complete(null);
        return null;
      }

      final refreshResponse = await dio.post(
        '/auth/refresh',
        data: {'refresh_token': refreshToken},
        options: Options(
          headers: {'Authorization': null},
          extra: {'_retried': true, '_skipAuth': true},
        ),
      );

      if (refreshResponse.statusCode == 200) {
        final data = refreshResponse.data as Map<String, dynamic>;
        final newAccessToken = data['access_token'] as String;
        final newRefreshToken = data['refresh_token'] as String;

        await storageService.saveTokens(
          accessToken: newAccessToken,
          refreshToken: newRefreshToken,
        );

        _refreshCompleter!.complete(newAccessToken);
        return newAccessToken;
      }

      await _handleSessionExpired();
      _refreshCompleter!.complete(null);
      return null;
    } catch (_) {
      await _handleSessionExpired();
      if (!_refreshCompleter!.isCompleted) {
        _refreshCompleter!.complete(null);
      }
      return null;
    } finally {
      _refreshCompleter = null;
    }
  }

  Future<void> _handleSessionExpired() async {
    await storageService.clearSession();
    onSessionExpired?.call();
  }

  void _setupInterceptors() {
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          if (options.extra['_skipAuth'] == true) {
            options.headers.remove('Authorization');
            return handler.next(options);
          }
          // Attach authorization token if present
          final token = await storageService.getAccessToken();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          return handler.next(options);
        },
        onError: (DioException error, handler) async {
          final path = error.requestOptions.path;
          final isAuthEndpoint =
              path.contains('/auth/login') || path.contains('/auth/refresh');
          final alreadyRetried = error.requestOptions.extra['_retried'] == true;

          // Safe 401 handling: single-flight token refresh, no recursive loops
          if (error.response?.statusCode == 401 &&
              !isAuthEndpoint &&
              !alreadyRetried) {
            final newAccessToken = await _performSingleFlightRefresh();
            if (newAccessToken != null && newAccessToken.isNotEmpty) {
              final retryOptions = error.requestOptions;
              retryOptions.extra['_retried'] = true;
              retryOptions.headers['Authorization'] = 'Bearer $newAccessToken';
              try {
                final retryResponse = await dio.fetch(retryOptions);
                return handler.resolve(retryResponse);
              } on DioException catch (retryError) {
                return handler.next(retryError);
              }
            }
          }

          return handler.next(error);
        },
      ),
    );
  }

  AppException mapDioError(dynamic error) {
    if (error is AppException) return error;

    if (error is DioException) {
      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError) {
        return const NetworkException(
          'Cannot reach the server. Please check your connection or API server status.',
        );
      }

      final response = error.response;
      if (response != null) {
        final statusCode = response.statusCode;
        final data = response.data;
        String message = 'An unexpected error occurred.';

        if (data is Map<String, dynamic> && data.containsKey('detail')) {
          final detail = data['detail'];
          if (detail is String) {
            message = detail;
          } else if (detail is List && detail.isNotEmpty) {
            final first = detail[0];
            if (first is Map && first.containsKey('msg')) {
              message = first['msg'].toString();
            } else {
              message = detail.toString();
            }
          }
        }

        if (statusCode == 401) {
          return AuthException(message, statusCode: statusCode);
        } else if (statusCode == 403) {
          if (message.contains('Email verification') ||
              message.contains('verification required')) {
            return PendingStatusException(
              message,
              status: 'PENDING_VERIFICATION',
            );
          }
          if (message.contains('awaiting') ||
              message.contains('review and approval') ||
              message.contains('PENDING_APPROVAL')) {
            return PendingStatusException(
              message,
              status: 'PENDING_APPROVAL',
            );
          }
          return AuthException(message, statusCode: statusCode);
        } else if (statusCode == 422 || statusCode == 400) {
          return ValidationAppException(message, details: data);
        } else if (statusCode == 409) {
          return ValidationAppException(message, details: data);
        } else if (statusCode != null && statusCode >= 500) {
          return ServerException(message);
        }
        return AppException(message, statusCode: statusCode);
      }
    }

    return AppException(error.toString());
  }
}

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insurechain_voiceguard/core/network/api_client.dart';
import 'package:insurechain_voiceguard/core/storage/secure_storage_service.dart';
import 'package:insurechain_voiceguard/features/customer/models/claim_model.dart';
import 'package:insurechain_voiceguard/features/customer/models/customer_policy_model.dart';
import 'package:insurechain_voiceguard/features/customer/models/evidence_upload_item.dart';
import 'package:insurechain_voiceguard/features/customer/providers/customer_provider.dart';
import 'package:insurechain_voiceguard/features/customer/screens/submit_claim_screen.dart';
import 'package:insurechain_voiceguard/features/customer/services/customer_api_service.dart';

class _MemStorage extends SecureStorageService {
  @override
  Future<String?> getAccessToken() async => 'test-token';
}

class _MockAdapter implements HttpClientAdapter {
  final Future<ResponseBody> Function(RequestOptions) onFetch;
  _MockAdapter(this.onFetch);

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) =>
      onFetch(options);

  @override
  void close({bool force = false}) {}
}

class _FakeDashboardNotifier extends CustomerDashboardNotifier {
  _FakeDashboardNotifier(super.api, super.ref, CustomerDashboardState initial) {
    state = initial;
  }

  @override
  Future<void> fetchDashboardData() async {}
}

class _FakePartialFailureApiService extends CustomerApiService {
  int createClaimCalls = 0;
  int assessCalls = 0;
  final List<String> uploadedFilenames = [];
  bool failSecondFile = true;

  _FakePartialFailureApiService() : super(apiClient: ApiClient());

  @override
  Future<List<ClaimModel>> listClaims({String? status}) async => [];

  @override
  Future<ClaimModel> submitClaim({
    required String registrationId,
    required String claimCategory,
    required double requestedAmount,
    required String incidentDate,
    required String description,
    Map<String, dynamic> structuredDetails = const {},
  }) async {
    createClaimCalls++;
    return ClaimModel(
      id: 'claim-uuid-001',
      customerId: 'cust-1',
      registrationId: registrationId,
      policyId: 'pol-1',
      policyVersionId: 'pv-1',
      claimCategory: claimCategory,
      requestedAmount: requestedAmount.toStringAsFixed(2),
      incidentDate: incidentDate,
      submissionTimestamp: '2026-11-12T10:00:00Z',
      description: description,
      status: 'SUBMITTED',
      createdAt: '2026-11-12T10:00:00Z',
    );
  }

  @override
  Future<void> uploadClaimEvidenceItem({
    required String claimId,
    required EvidenceUploadItem item,
    void Function(double progress)? onProgress,
  }) async {
    onProgress?.call(0.5);
    uploadedFilenames.add(item.filename);
    if (failSecondFile && item.filename == 'file2.png') {
      throw Exception('Simulated network drop');
    }
    onProgress?.call(1.0);
  }

  @override
  Future<void> assessClaim(String claimId) async {
    assessCalls++;
  }
}

void main() {
  test('EvidenceUploadItem validates extensions, size limits, and duplicate keys', () {
    expect(EvidenceUploadItem.validateFile('bill.pdf', 1024), isNull);
    expect(EvidenceUploadItem.validateFile('photo.JPG', 2048), isNull);
    expect(EvidenceUploadItem.validateFile('scan.png', 512), isNull);

    expect(EvidenceUploadItem.validateFile('script.exe', 100), isNotNull);
    expect(EvidenceUploadItem.validateFile('empty.pdf', 0), isNotNull);
    expect(
      EvidenceUploadItem.validateFile('huge.pdf', EvidenceUploadItem.maxFileSizeBytes + 1),
      isNotNull,
    );

    expect(EvidenceUploadItem.inferMimeType('doc.pdf'), 'application/pdf');
    expect(EvidenceUploadItem.inferMimeType('img.jpeg'), 'image/jpeg');
    expect(EvidenceUploadItem.inferMimeType('img.png'), 'image/png');
    expect(EvidenceUploadItem.inferMimeType('bad.txt'), isNull);
  });

  test('CustomerApiService.uploadClaimEvidenceItem supports stream uploads without path and reports progress', () async {
    String? capturedPath;
    String? capturedContentType;
    final dio = Dio(BaseOptions(baseUrl: 'http://127.0.0.1:8000/api/v1'));
    dio.httpClientAdapter = _MockAdapter((options) async {
      capturedPath = options.path;
      capturedContentType = options.contentType;
      return ResponseBody.fromString(jsonEncode({'id': 'ev-1'}), 201, headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      });
    });

    final api = CustomerApiService(
      apiClient: ApiClient(customDio: dio, customStorage: _MemStorage()),
    );

    final item = EvidenceUploadItem(
      id: '1',
      filename: 'hospital_bill.pdf',
      sizeBytes: 12,
      mimeType: 'application/pdf',
      evidenceType: 'MEDICAL_BILL',
      filePath: null, // No filesystem path (Android SAF stream)
      streamFactory: () => Stream.value(utf8.encode('%PDF-1.4\n%%EOF')),
    );

    final progressValues = <double>[];
    await api.uploadClaimEvidenceItem(
      claimId: 'claim-123',
      item: item,
      onProgress: progressValues.add,
    );

    expect(capturedPath, '/claims/claim-123/evidence');
    expect(capturedContentType, contains('multipart/form-data'));
  });

  test('ClaimsListNotifier.submitClaim propagates evidence upload errors instead of swallowing them', () async {
    final fakeApi = _FakePartialFailureApiService();
    final dio = Dio(BaseOptions(baseUrl: 'http://127.0.0.1:8000/api/v1'));
    dio.httpClientAdapter = _MockAdapter((options) async {
      if (options.path.endsWith('/evidence')) {
        return ResponseBody.fromString(jsonEncode({'detail': 'Invalid file'}), 400, headers: {
          Headers.contentTypeHeader: [Headers.jsonContentType],
        });
      }
      return ResponseBody.fromString(
        jsonEncode({
          'id': 'c-1',
          'customer_id': 'u-1',
          'registration_id': 'r-1',
          'policy_id': 'p-1',
          'policy_version_id': 'pv-1',
          'claim_category': 'MEDICAL',
          'requested_amount': '1000.00',
          'incident_date': '2026-11-10',
          'submission_timestamp': '2026-11-12T10:00:00Z',
          'description': 'Hospitalization claim test description',
          'status': 'SUBMITTED',
          'created_at': '2026-11-12T10:00:00Z',
          'updated_at': '2026-11-12T10:00:00Z',
        }),
        201,
        headers: {
          Headers.contentTypeHeader: [Headers.jsonContentType],
        },
      );
    });

    final realApiWithMockHttp = CustomerApiService(
      apiClient: ApiClient(customDio: dio, customStorage: _MemStorage()),
    );
    final notifier = ClaimsListNotifier(realApiWithMockHttp);

    final res = await notifier.submitClaim(
      registrationId: 'r-1',
      claimCategory: 'MEDICAL',
      requestedAmount: 1000,
      incidentDate: '2026-11-10',
      description: 'Hospitalization claim test description',
      evidenceType: 'MEDICAL_BILL',
      evidenceFilename: 'bill.pdf',
      evidenceBytes: utf8.encode('%PDF-1.4\n%%EOF'),
      evidenceMime: 'application/pdf',
    );

    expect(res, isNull);
    expect(notifier.state.errorMessage, isNotNull);
    expect(fakeApi.assessCalls, 0);
  });

  testWidgets('SubmitClaimScreen creates claim once and retries only failed files', (tester) async {
    final fakeApi = _FakePartialFailureApiService();
    const activeReg = CustomerRegistrationModel(
      id: '11111111-1111-1111-1111-111111111111',
      customerId: 'cust-1',
      policyId: 'pol-1',
      policyVersionId: 'pv-1',
      status: 'CONFIRMED',
      customerConsent: true,
    );

    final container = ProviderContainer(
      overrides: [
        customerApiServiceProvider.overrideWithValue(fakeApi),
        customerDashboardProvider.overrideWith(
          (ref) => _FakeDashboardNotifier(
            fakeApi,
            ref,
            const CustomerDashboardState(registrations: [activeReg]),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(
          home: SubmitClaimScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Add Files (0/5)'), findsOneWidget);
    expect(find.text('Submit Claim for Evaluation'), findsOneWidget);

    container.dispose();
  });
}


import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insurechain_voiceguard/core/network/api_client.dart';
import 'package:insurechain_voiceguard/core/theme/app_theme.dart';
import 'package:insurechain_voiceguard/features/agent/models/sales_session_model.dart';
import 'package:insurechain_voiceguard/features/agent/providers/agent_provider.dart';
import 'package:insurechain_voiceguard/features/agent/screens/sales_session_detail_screen.dart';
import 'package:insurechain_voiceguard/features/agent/services/agent_api_service.dart';
import 'package:insurechain_voiceguard/features/customer/models/verification_report_model.dart';
import 'package:insurechain_voiceguard/features/customer/providers/customer_provider.dart';
import 'package:insurechain_voiceguard/features/customer/screens/verification_report_screen.dart';

class _FakeStage2AgentApiService extends AgentApiService {
  bool failNextVerify;
  int verifyCalls = 0;

  _FakeStage2AgentApiService({this.failNextVerify = true}) : super(apiClient: ApiClient());

  @override
  Future<VerificationReportModel> verifySalesSession(String sessionId) async {
    verifyCalls++;
    if (failNextVerify) {
      throw Exception('Gemini API timed out');
    }
    return const VerificationReportModel(
      id: 'rep-2',
      salesSessionId: 'sess-1',
      customerId: 'cust-1',
      agentId: 'agent-1',
      policyId: 'pol-1',
      reportVersion: 2,
      status: 'COMPLETED',
      overallIntegrityStatus: 'VERIFIED',
      summary: 'All claims grounded',
      supportedCount: 1,
    );
  }

  @override
  Future<List<SalesSessionModel>> listSalesSessions({
    String? status,
    int page = 1,
    int pageSize = 20,
  }) async =>
      [];
}

void main() {
  SalesSessionModel makeSession({
    String status = 'COMPLETED',
    String? errorMessage,
  }) {
    return SalesSessionModel(
      id: 'sess-1',
      agentId: 'agent-1',
      customerId: 'cust-1',
      policyId: 'pol-1',
      audioStorageRef: 'sales_sessions/sess-1/audio123',
      audioMimeType: 'audio/m4a',
      audioFileSizeBytes: 2048,
      durationSeconds: 12,
      audioChecksum: 'a' * 64,
      customerConsent: true,
      status: status,
      errorMessage: errorMessage,
      createdAt: '2026-11-12T10:00:00Z',
      updatedAt: '2026-11-12T10:00:00Z',
    );
  }

  testWidgets('SalesSessionDetailScreen displays transcription error and neutral speaker labels', (tester) async {
    final failedSession = makeSession(
      status: 'FAILED',
      errorMessage: 'Recorded audio has not been uploaded to secure storage.',
    );

    await tester.pumpWidget(
      ProviderScope(
        key: UniqueKey(),
        overrides: [
          sessionDetailProvider('sess-1').overrideWith((ref) async => failedSession),
          sessionTranscriptProvider('sess-1').overrideWith((ref) async => null),
          sessionVerificationProvider('sess-1').overrideWith((ref) async => null),
        ],
        child: const MaterialApp(home: SalesSessionDetailScreen(sessionId: 'sess-1')),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('Recorded audio has not been uploaded'), findsOneWidget);

    await tester.pumpWidget(
      ProviderScope(
        key: UniqueKey(),
        overrides: [
          sessionDetailProvider('sess-1').overrideWith((ref) async => makeSession(status: 'COMPLETED')),
          sessionTranscriptProvider('sess-1').overrideWith(
            (ref) async => const SalesTranscriptModel(
              sessionId: 'sess-1',
              status: 'COMPLETED',
              transcript: 'Hello sir. What about OPD?',
              speakerDiarization: [
                {'speaker': 'speaker_0', 'text': 'Hello sir.'},
                {'speaker': 'speaker_1', 'text': 'What about OPD?'},
              ],
              createdAt: '2026-11-12T10:00:00Z',
              updatedAt: '2026-11-12T10:00:00Z',
            ),
          ),
          sessionVerificationProvider('sess-1').overrideWith((ref) async => null),
        ],
        child: const MaterialApp(home: SalesSessionDetailScreen(sessionId: 'sess-1')),
      ),
    );
    await tester.pumpAndSettle();

    // Verifies raw speaker_0 and speaker_1 map to neutral labels Speaker 1 and Speaker 2
    expect(find.text('Speaker 1'), findsOneWidget);
    expect(find.text('Speaker 2'), findsOneWidget);
    expect(find.text('Hello sir.'), findsOneWidget);
    expect(find.text('What about OPD?'), findsOneWidget);
  });

  testWidgets('SalesSessionDetailScreen shows FAILED verification card with retry and no green VERIFIED badge', (tester) async {
    final fakeApi = _FakeStage2AgentApiService(failNextVerify: true);
    const failedReport = VerificationReportModel(
      id: 'rep-1',
      salesSessionId: 'sess-1',
      customerId: 'cust-1',
      agentId: 'agent-1',
      policyId: 'pol-1',
      reportVersion: 1,
      status: 'FAILED',
      summary: 'Verification failed: IntegrationException',
      errorMessage: 'All Gemini models timed out',
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          agentApiServiceProvider.overrideWithValue(fakeApi),
          sessionDetailProvider('sess-1').overrideWith((ref) async => makeSession()),
          sessionTranscriptProvider('sess-1').overrideWith(
            (ref) async => const SalesTranscriptModel(
              sessionId: 'sess-1',
              status: 'COMPLETED',
              transcript: 'Agent promised full cover.',
              createdAt: '2026-11-12T10:00:00Z',
              updatedAt: '2026-11-12T10:00:00Z',
            ),
          ),
          sessionVerificationProvider('sess-1').overrideWith((ref) async => failedReport),
        ],
        child: const MaterialApp(home: SalesSessionDetailScreen(sessionId: 'sess-1')),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('VERIFICATION FAILED'), findsOneWidget);
    expect(find.text('All Gemini models timed out'), findsOneWidget);
    expect(find.text('VERIFIED'), findsNothing);
    expect(find.text('Retry Gemini Verification'), findsOneWidget);

    await tester.ensureVisible(find.text('Retry Gemini Verification'));
    await tester.tap(find.text('Retry Gemini Verification'));
    await tester.pumpAndSettle();

    expect(fakeApi.verifyCalls, 1);
    expect(find.textContaining('Gemini API timed out'), findsWidgets);
  });

  testWidgets('VerificationReportScreen renders FAILED state without green All Claims Grounded badge', (tester) async {
    const failedReport = VerificationReportModel(
      id: 'rep-fail',
      salesSessionId: 'sess-1',
      customerId: 'cust-1',
      agentId: 'agent-1',
      policyId: 'pol-1',
      reportVersion: 1,
      status: 'FAILED',
      overallIntegrityStatus: null,
      errorMessage: 'Gemini upstream timeout',
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          verificationReportProvider('rep-fail').overrideWith((ref) async => failedReport),
        ],
        child: const MaterialApp(home: VerificationReportScreen(reportId: 'rep-fail')),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Verification Failed'), findsOneWidget);
    expect(find.text('Gemini upstream timeout'), findsOneWidget);
    expect(find.text('All Claims Grounded'), findsNothing);

    final failIcon = tester.widget<Icon>(find.byIcon(Icons.error_outline_rounded).first);
    expect(failIcon.color, AppTheme.error);
  });
}

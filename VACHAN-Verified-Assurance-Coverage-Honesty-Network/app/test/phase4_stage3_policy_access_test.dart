import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:insurechain_voiceguard/core/network/api_client.dart';
import 'package:insurechain_voiceguard/features/customer/models/customer_policy_model.dart';
import 'package:insurechain_voiceguard/features/customer/providers/customer_provider.dart';
import 'package:insurechain_voiceguard/features/customer/screens/policy_detail_screen.dart';
import 'package:insurechain_voiceguard/features/customer/services/customer_api_service.dart';

class _FakeStage3CustomerApiService extends CustomerApiService {
  bool failNextUrl;
  int documentUrlCallCount = 0;
  static const String testUrl = 'https://api.cloudinary.com/v1_1/demo/raw/private/signed.pdf';

  _FakeStage3CustomerApiService({
    this.failNextUrl = false,
  }) : super(apiClient: ApiClient());

  @override
  Future<DetailedPolicyModel> getPolicyDetails(String policyId) async {
    return DetailedPolicyModel(
      id: policyId,
      insurerName: 'VACHAN Assurance',
      policyName: 'Care Health Premier',
      policyCode: 'CHP-001',
      category: 'HEALTH',
      description: 'Comprehensive health coverage with full hospitalization.',
      coverageLimit: 500000.0,
      waitingPeriodDays: 30,
      claimFilingWindowDays: 30,
      isActive: true,
      latestVersion: PolicyVersionModel(
        id: 'ver-1',
        policyId: policyId,
        versionNumber: 1,
        documentStorageRef: 'policies/$policyId/v1_doc.pdf',
        documentChecksum: 'a' * 64,
        effectiveDate: '2026-01-01',
        termsJson: {'hospitalization': 'Covered 100%'},
        isPublished: true,
      ),
    );
  }

  @override
  Future<String> getPublishedPolicyDocumentUrl(String policyId, String versionId) async {
    documentUrlCallCount++;
    if (failNextUrl) {
      throw Exception('Signed document URL generation failed (403)');
    }
    return testUrl;
  }
}

void main() {
  testWidgets('PolicyDetailScreen displays View Policy PDF button for published version and triggers signed URL fetch', (tester) async {
    final fakeApi = _FakeStage3CustomerApiService(failNextUrl: false);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          customerApiServiceProvider.overrideWithValue(fakeApi),
        ],
        child: MaterialApp(
          home: PolicyDetailScreen(
            policyId: 'pol-1',
            onLaunchUrl: (uri, {LaunchMode? mode}) async => true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Verify published policy version header and View Policy PDF button appear
    expect(find.text('Published Policy Version'), findsOneWidget);
    expect(find.text('Version #1'), findsOneWidget);
    final buttonFinder = find.byKey(const Key('view_policy_pdf_button'));
    expect(buttonFinder, findsOneWidget);
    expect(find.text('View Policy PDF'), findsOneWidget);

    // Scroll to button and tap to fetch signed URL
    await tester.ensureVisible(buttonFinder);
    await tester.pumpAndSettle();
    await tester.tap(buttonFinder);
    await tester.pump();

    // Verify API called
    expect(fakeApi.documentUrlCallCount, 1);
  });

  testWidgets('PolicyDetailScreen handles failed URL retrieval and displays error state', (tester) async {
    final fakeApi = _FakeStage3CustomerApiService(failNextUrl: true);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          customerApiServiceProvider.overrideWithValue(fakeApi),
        ],
        child: MaterialApp(
          home: PolicyDetailScreen(
            policyId: 'pol-1',
            onLaunchUrl: (uri, {LaunchMode? mode}) async => true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final buttonFinder = find.byKey(const Key('view_policy_pdf_button'));
    expect(buttonFinder, findsOneWidget);

    // Scroll to button and tap
    await tester.ensureVisible(buttonFinder);
    await tester.pumpAndSettle();
    await tester.tap(buttonFinder);
    await tester.pumpAndSettle();

    // Verify error feedback is rendered
    expect(fakeApi.documentUrlCallCount, 1);
    expect(find.textContaining('Signed document URL generation failed'), findsWidgets);
  });

  testWidgets('PolicyDetailScreen requests a fresh URL upon re-tap (handling expired signed URLs gracefully)', (tester) async {
    final fakeApi = _FakeStage3CustomerApiService(failNextUrl: false);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          customerApiServiceProvider.overrideWithValue(fakeApi),
        ],
        child: MaterialApp(
          home: PolicyDetailScreen(
            policyId: 'pol-1',
            onLaunchUrl: (uri, {LaunchMode? mode}) async => true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final buttonFinder = find.byKey(const Key('view_policy_pdf_button'));

    // Scroll into view
    await tester.ensureVisible(buttonFinder);
    await tester.pumpAndSettle();

    // First request (initial view)
    await tester.tap(buttonFinder);
    await tester.pump(const Duration(milliseconds: 200));
    expect(fakeApi.documentUrlCallCount, 1);

    // Re-tap after expiry: requests a fresh signed URL without caching expired link
    await tester.tap(buttonFinder);
    await tester.pump(const Duration(milliseconds: 200));
    expect(fakeApi.documentUrlCallCount, 2);
  });

  testWidgets('PolicyDetailScreen does not expose View Policy PDF action when no published version exists', (tester) async {
    final draftOnlyApi = _FakeStage3CustomerApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          customerApiServiceProvider.overrideWithValue(draftOnlyApi),
          policyDetailFutureProvider('draft-pol').overrideWith((ref) async => const DetailedPolicyModel(
            id: 'draft-pol',
            insurerName: 'VACHAN',
            policyName: 'Draft Health Plan',
            policyCode: 'DHP-001',
            category: 'HEALTH',
            coverageLimit: 100000.0,
            waitingPeriodDays: 30,
            claimFilingWindowDays: 30,
            isActive: false,
            latestVersion: null, // Draft only, no published version
          )),
        ],
        child: const MaterialApp(
          home: PolicyDetailScreen(policyId: 'draft-pol'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Verify document action is NOT rendered for unpublished drafts
    expect(find.text('Published Policy Version'), findsNothing);
    expect(find.byKey(const Key('view_policy_pdf_button')), findsNothing);
  });
}

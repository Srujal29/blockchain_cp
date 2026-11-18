import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insurechain_voiceguard/core/errors/app_exception.dart';
import 'package:insurechain_voiceguard/core/network/api_client.dart';
import 'package:insurechain_voiceguard/core/storage/secure_storage_service.dart';
import 'package:insurechain_voiceguard/core/theme/app_theme.dart';
import 'package:insurechain_voiceguard/features/agent/providers/agent_provider.dart';
import 'package:insurechain_voiceguard/features/agent/screens/new_sales_session_screen.dart';
import 'package:insurechain_voiceguard/features/auth/providers/auth_provider.dart';
import 'package:insurechain_voiceguard/features/auth/screens/account_pending_screen.dart';
import 'package:insurechain_voiceguard/features/auth/services/auth_api_service.dart';
import 'package:insurechain_voiceguard/features/authority/providers/authority_provider.dart';
import 'package:insurechain_voiceguard/features/authority/screens/authority_claim_review_screen.dart';
import 'package:insurechain_voiceguard/features/authority/screens/authority_home_screen.dart';
import 'package:insurechain_voiceguard/features/authority/services/authority_api_service.dart';
import 'package:insurechain_voiceguard/features/customer/models/claim_model.dart';
import 'package:insurechain_voiceguard/features/customer/models/customer_policy_model.dart';
import 'package:insurechain_voiceguard/features/customer/providers/customer_provider.dart';
import 'package:insurechain_voiceguard/features/customer/screens/claim_detail_screen.dart';
import 'package:insurechain_voiceguard/features/customer/screens/claims_list_screen.dart';
import 'package:insurechain_voiceguard/features/customer/services/customer_api_service.dart';
import 'package:insurechain_voiceguard/shared/widgets/status_badge.dart';

ClaimModel _makeClaim({
  required String id,
  required String status,
  String? overallOutcome,
  List<ClaimStatusHistoryModel> statusHistory = const [],
}) {
  return ClaimModel(
    id: id,
    registrationId: 'reg-1',
    customerId: 'cust-1',
    policyId: 'pol-1',
    policyVersionId: 'ver-1',
    claimCategory: 'MEDICAL',
    incidentDate: '2026-11-01',
    submissionTimestamp: '2026-11-10T10:00:00Z',
    description: 'Hospitalization bill claim',
    requestedAmount: '5000.00',
    status: status,
    createdAt: '2026-11-10T10:00:00Z',
    latestAssessment: overallOutcome == null
        ? null
        : ClaimAssessmentModel(
            id: 'assess-1',
            claimId: id,
            assessmentVersion: 1,
            overallOutcome: overallOutcome,
            requestedAmount: '5000.00',
            applicableLimit: '10000.00',
            potentiallyPayableAmount: '5000.00',
            excessAmount: '0.00',
            missingEvidence: const [],
            reviewFlags: const [],
            rulesEvaluated: const [],
          ),
    statusHistory: statusHistory,
  );
}

class _FakeCustomerApiService extends CustomerApiService {
  final List<String?> requestedStatuses = [];
  ClaimModel? detailClaim;

  _FakeCustomerApiService({this.detailClaim}) : super(apiClient: ApiClient());

  @override
  Future<List<ClaimModel>> listClaims({String? status}) async {
    requestedStatuses.add(status);
    return [
      _makeClaim(id: 'claim-11111111', status: 'SUBMITTED'),
      _makeClaim(id: 'claim-22222222', status: 'UNDER_REVIEW'),
    ];
  }

  @override
  Future<ClaimModel> getClaimDetails(String claimId) async {
    return detailClaim ?? _makeClaim(id: claimId, status: 'UNDER_REVIEW');
  }
}

class _FakeAuthorityApiService extends AuthorityApiService {
  final List<String?> requestedStatuses = [];
  final List<ClaimModel> claims;
  final List<Map<String, dynamic>> duplicates;

  _FakeAuthorityApiService({
    this.claims = const [],
    this.duplicates = const [],
  }) : super(apiClient: ApiClient());

  @override
  Future<List<ClaimModel>> listAllClaims({
    String? status,
    int page = 1,
    int pageSize = 100,
  }) async {
    requestedStatuses.add(status);
    return claims;
  }

  @override
  Future<ClaimModel> getClaimDetails(String claimId) async {
    return claims.firstWhere((c) => c.id == claimId);
  }

  @override
  Future<List<Map<String, dynamic>>> checkDuplicates(String claimId) async {
    return duplicates;
  }
}

class _FakeStorage extends SecureStorageService {
  @override
  Future<String?> getAccessToken() async => null;
}

class _FakeAuthApiService extends AuthApiService {
  String? lastCheckedEmail;
  _FakeAuthApiService() : super(client: ApiClient());

  @override
  Future<AuthResponse> login({required String email, required String password}) async {
    lastCheckedEmail = email;
    throw const PendingStatusException(
      'Account is awaiting administrator review and approval.',
      status: 'PENDING_APPROVAL',
    );
  }
}

void main() {
  testWidgets('Customer ClaimsListScreen Under Review chip uses UNDER_REVIEW', (tester) async {
    final fakeApi = _FakeCustomerApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          customerApiServiceProvider.overrideWithValue(fakeApi),
        ],
        child: const MaterialApp(home: ClaimsListScreen()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Under Review'));
    await tester.pumpAndSettle();

    expect(fakeApi.requestedStatuses, contains('UNDER_REVIEW'));
    expect(fakeApi.requestedStatuses, isNot(contains('IN_REVIEW')));
  });

  testWidgets('AuthorityHomeScreen uses UNDER_REVIEW and preserves KPI counts when filtering', (tester) async {
    final fakeAuthApi = _FakeAuthorityApiService(
      claims: [
        _makeClaim(id: 'c1-11111111', status: 'SUBMITTED'),
        _makeClaim(id: 'c2-22222222', status: 'UNDER_REVIEW'),
        _makeClaim(id: 'c3-33333333', status: 'APPROVED'),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authorityApiServiceProvider.overrideWithValue(fakeAuthApi),
        ],
        child: const MaterialApp(home: AuthorityHomeScreen()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('In Review (1)'), findsOneWidget);
    expect(find.text('Submitted (1)'), findsOneWidget);

    await tester.tap(find.text('In Review (1)'));
    await tester.pumpAndSettle();

    // KPI counts remain intact and no IN_REVIEW API filter call is sent.
    expect(find.text('Submitted (1)'), findsOneWidget);
    expect(find.text('In Review (1)'), findsOneWidget);
    expect(find.text('Approved (1)'), findsOneWidget);
    expect(fakeAuthApi.requestedStatuses, isNot(contains('IN_REVIEW')));
  });

  testWidgets('AuthorityClaimReviewScreen shows lifecycle buttons per status and guards substrings', (tester) async {
    Future<void> pumpClaim(String status) async {
      final claim = _makeClaim(
        id: 'claim-12345678',
        status: status,
        overallOutcome: 'INELIGIBLE',
        statusHistory: const [
          ClaimStatusHistoryModel(
            id: 'h1',
            previousStatus: 'NEW',
            newStatus: 'SUBMITTED',
            actorRole: 'CUSTOMER',
            reason: 'Initial submission',
            createdAt: '2026-11-12', // < 19 chars
          ),
        ],
      );
      final fakeApi = _FakeAuthorityApiService(
        claims: [claim],
        duplicates: const [
          {'candidate_claim_id': 'abc', 'match_score': 0.91, 'incident_date': '2026-11-01'},
          {'candidate_claim_id': '', 'match_score': 0.50, 'incident_date': null},
        ],
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            authorityApiServiceProvider.overrideWithValue(fakeApi),
          ],
          child: const MaterialApp(
            home: AuthorityClaimReviewScreen(claimId: 'claim-12345678'),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    // 1. SUBMITTED -> Start Review only
    await pumpClaim('SUBMITTED');
    expect(find.text('Start Review'), findsOneWidget);
    expect(find.text('Approve'), findsNothing);
    expect(find.text('Candidate #abc • Match Score: 0.91 • Date: 2026-11-01'), findsOneWidget);
    expect(find.text('Candidate #UNKNOWN • Match Score: 0.50 • Date: N/A'), findsOneWidget);
    expect(find.text('2026-11-12'), findsOneWidget);

    // INELIGIBLE badge uses AppTheme.error
    final badge = tester.widget<StatusBadge>(find.byWidgetPredicate(
      (w) => w is StatusBadge && w.label == 'INELIGIBLE',
    ));
    expect(badge.color, AppTheme.error);

    // 2. EVIDENCE_REQUESTED -> Resume Review only
    await pumpClaim('EVIDENCE_REQUESTED');
    expect(find.text('Resume Review'), findsOneWidget);
    expect(find.text('Approve'), findsNothing);

    // 3. UNDER_REVIEW -> Approve / Evidence / Reject
    await pumpClaim('UNDER_REVIEW');
    expect(find.text('Approve'), findsOneWidget);
    expect(find.text('Evidence'), findsOneWidget);
    expect(find.text('Reject'), findsOneWidget);

    // 4. APPROVED -> Execute Simulated Settlement Payment only
    await pumpClaim('APPROVED');
    expect(find.text('Execute Simulated Settlement Payment (Audit Record)'), findsOneWidget);
    expect(find.text('Approve'), findsNothing);
  });

  testWidgets('Customer ClaimDetailScreen maps ELIGIBLE, NEEDS_REVIEW, and INELIGIBLE colors', (tester) async {
    Future<Color> pumpOutcome(String outcome) async {
      final fakeApi = _FakeCustomerApiService(
        detailClaim: _makeClaim(
          id: 'claim-cust-1',
          status: 'UNDER_REVIEW',
          overallOutcome: outcome,
        ),
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            customerApiServiceProvider.overrideWithValue(fakeApi),
          ],
          child: const MaterialApp(
            home: ClaimDetailScreen(claimId: 'claim-cust-1'),
          ),
        ),
      );
      await tester.pumpAndSettle();

      final expectedLabel = outcome.replaceAll('_', ' ');
      final badge = tester.widget<StatusBadge>(find.byWidgetPredicate(
        (w) => w is StatusBadge && w.label == expectedLabel,
      ));
      return badge.color;
    }

    expect(await pumpOutcome('ELIGIBLE'), AppTheme.success);
    expect(await pumpOutcome('NEEDS_REVIEW'), AppTheme.warning);
    expect(await pumpOutcome('INELIGIBLE'), AppTheme.error);
  });

  test('CustomerRegistrationModel treats PENDING_REVIEW as awaiting confirmation', () {
    final pendingReview = CustomerRegistrationModel.fromJson({
      'id': 'reg-1',
      'policy_id': 'pol-1',
      'policy_version_id': 'ver-1',
      'status': 'PENDING_REVIEW',
      'customer_consent': false,
    });
    final confirmed = CustomerRegistrationModel.fromJson({
      'id': 'reg-2',
      'policy_id': 'pol-1',
      'policy_version_id': 'ver-1',
      'status': 'CONFIRMED',
      'customer_consent': true,
    });

    expect(pendingReview.isAwaitingConfirmation, isTrue);
    expect(confirmed.isAwaitingConfirmation, isFalse);
  });

  testWidgets('NewSalesSessionScreen disables submit when no policies exist and syncs default policy', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          agentPoliciesProvider.overrideWith((ref) async => <DetailedPolicyModel>[]),
        ],
        child: const MaterialApp(home: NewSalesSessionScreen()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('No published policies available'), findsOneWidget);
    final submitBtn = tester.widget<ElevatedButton>(find.byWidgetPredicate(
      (w) => w is ElevatedButton && find.descendant(of: find.byWidget(w), matching: find.text('Submit Session to VoiceGuard')).evaluate().isNotEmpty,
    ));
    expect(submitBtn.onPressed, isNull);

    // When a policy is present, dropdown selects it without staying null
    await tester.pumpWidget(
      ProviderScope(
        key: UniqueKey(),
        overrides: [
          agentPoliciesProvider.overrideWith(
            (ref) async => const [
              DetailedPolicyModel(
                id: 'pol-default-1',
                insurerName: 'VACHAN',
                policyName: 'Health Shield',
                policyCode: 'HS-01',
                category: 'MEDICAL',
                description: 'Full cover',
                coverageLimit: 100000,
                waitingPeriodDays: 30,
                claimFilingWindowDays: 30,
                isActive: true,
              ),
            ],
          ),
        ],
        child: const MaterialApp(home: NewSalesSessionScreen()),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Health Shield (MEDICAL)'), findsOneWidget);
  });

  testWidgets('AccountPendingScreen checks approval status via login without kicking to /welcome', (tester) async {
    final fakeAuthApi = _FakeAuthApiService();
    final fakeStorage = _FakeStorage();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          secureStorageProvider.overrideWithValue(fakeStorage),
          authApiServiceProvider.overrideWithValue(fakeAuthApi),
          authProvider.overrideWith((ref) {
            final notifier = AuthNotifier(
              authService: fakeAuthApi,
              storageService: fakeStorage,
            );
            notifier.state = AuthState.pendingApproval(null, email: 'pending.agent@example.com');
            return notifier;
          }),
        ],
        child: const MaterialApp(home: AccountPendingScreen()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Check Approval Status'));
    await tester.pumpAndSettle();

    expect(find.text('Verify Approval Status'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'Password123!');
    await tester.tap(find.text('Check Status'));
    await tester.pumpAndSettle();

    expect(fakeAuthApi.lastCheckedEmail, 'pending.agent@example.com');
    expect(find.textContaining('awaiting administrator review'), findsOneWidget);
  });
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insurechain_voiceguard/core/network/api_client.dart';
import 'package:insurechain_voiceguard/features/auth/models/user_model.dart';
import 'package:insurechain_voiceguard/features/authority/models/authority_models.dart';
import 'package:insurechain_voiceguard/features/authority/providers/authority_provider.dart';
import 'package:insurechain_voiceguard/features/authority/screens/authority_agents_screen.dart';
import 'package:insurechain_voiceguard/features/authority/screens/authority_policies_screen.dart';
import 'package:insurechain_voiceguard/features/authority/screens/authority_policy_detail_screen.dart';
import 'package:insurechain_voiceguard/features/authority/services/authority_api_service.dart';
import 'package:insurechain_voiceguard/features/customer/models/customer_policy_model.dart';

class _FakeAuthorityApiService extends AuthorityApiService {
  String? lastAgentDecisionStatus;
  String? lastAgentDecisionReason;
  String? lastCreatedPolicyCode;
  String? lastPublishedVersionId;

  _FakeAuthorityApiService() : super(apiClient: ApiClient());

  @override
  Future<AuthorityAgentPageModel> listAgents({
    String? status,
    int page = 1,
    int pageSize = 20,
  }) async {
    return const AuthorityAgentPageModel(
      items: [
        UserModel(
          id: 'agent-111',
          email: 'agent1@example.com',
          fullName: 'Rahul Agent',
          phone: '9876543210',
          role: UserRole.insuranceAgent,
          accountStatus: AccountStatus.pendingApproval,
        ),
      ],
      total: 1,
      page: 1,
      pageSize: 20,
    );
  }

  @override
  Future<UserModel> approveOrRejectAgent({
    required String userId,
    required String status,
    String? reason,
  }) async {
    lastAgentDecisionStatus = status;
    lastAgentDecisionReason = reason;
    return UserModel(
      id: userId,
      email: 'agent1@example.com',
      fullName: 'Rahul Agent',
      role: UserRole.insuranceAgent,
      accountStatus:
          status == 'ACTIVE' ? AccountStatus.active : AccountStatus.rejected,
    );
  }

  @override
  Future<List<AuthorityPolicyModel>> listManagePolicies({String? category}) async {
    return [
      const AuthorityPolicyModel(
        id: 'pol-draft-1',
        insurerName: 'Care Premier',
        policyName: 'Draft Health Plan',
        policyCode: 'DRF-001',
        category: 'HOSPITALIZATION',
        description: 'Draft policy pending PDF upload',
        coverageLimit: 500000,
        waitingPeriodDays: 30,
        claimFilingWindowDays: 30,
        isActive: true,
        versions: [
          PolicyVersionModel(
            id: 'ver-draft-1',
            policyId: 'pol-draft-1',
            versionNumber: 1,
            documentStorageRef: 'policies/pol-draft-1/v1_abc',
            documentChecksum: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            effectiveDate: '2026-11-12',
            isPublished: false,
          ),
        ],
      ),
    ];
  }

  @override
  Future<AuthorityPolicyModel> getManagePolicyDetail(String policyId) async {
    final list = await listManagePolicies();
    return list.first;
  }

  @override
  Future<AuthorityPolicyModel> createPolicy({
    required String insurerName,
    required String policyName,
    required String policyCode,
    required String category,
    required String description,
    required double coverageLimit,
    int waitingPeriodDays = 0,
    int claimFilingWindowDays = 30,
  }) async {
    lastCreatedPolicyCode = policyCode;
    return AuthorityPolicyModel(
      id: 'pol-new-1',
      insurerName: insurerName,
      policyName: policyName,
      policyCode: policyCode,
      category: category,
      description: description,
      coverageLimit: coverageLimit,
      waitingPeriodDays: waitingPeriodDays,
      claimFilingWindowDays: claimFilingWindowDays,
      isActive: true,
    );
  }

  @override
  Future<PolicyVersionModel> publishPolicyVersion(
      String policyId, String versionId) async {
    lastPublishedVersionId = versionId;
    return PolicyVersionModel(
      id: versionId,
      policyId: policyId,
      versionNumber: 1,
      documentStorageRef: 'policies/pol-draft-1/v1_abc',
      documentChecksum:
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      effectiveDate: '2026-11-12',
      isPublished: true,
    );
  }
}

void main() {
  testWidgets('AuthorityAgentsScreen lists agents and enforces >= 5 char rejection reason',
      (tester) async {
    final fakeApi = _FakeAuthorityApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authorityApiServiceProvider.overrideWithValue(fakeApi),
        ],
        child: const MaterialApp(home: AuthorityAgentsScreen()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Rahul Agent'), findsOneWidget);

    await tester.tap(find.text('Rahul Agent'));
    await tester.pumpAndSettle();

    expect(find.text('Approve Agent'), findsOneWidget);
    expect(find.text('Reject'), findsOneWidget);

    await tester.tap(find.text('Reject'));
    await tester.pumpAndSettle();

    // Short reason (< 5 chars) must show validation error
    await tester.enterText(find.byType(TextField), 'no');
    await tester.tap(find.text('Confirm Reject'));
    await tester.pumpAndSettle();
    expect(find.text('Reason must be at least 5 characters.'), findsOneWidget);

    // Valid reason (>= 5 chars) submits rejection
    await tester.enterText(find.byType(TextField), 'Missing IRDAI license');
    await tester.tap(find.text('Confirm Reject'));
    await tester.pumpAndSettle();

    expect(fakeApi.lastAgentDecisionStatus, 'REJECTED');
    expect(fakeApi.lastAgentDecisionReason, 'Missing IRDAI license');
  });

  testWidgets('AuthorityPoliciesScreen shows draft badge and filters', (tester) async {
    final fakeApi = _FakeAuthorityApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authorityApiServiceProvider.overrideWithValue(fakeApi),
        ],
        child: const MaterialApp(home: AuthorityPoliciesScreen()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Draft Health Plan'), findsOneWidget);
    expect(find.text('DRAFT'), findsNWidgets(2)); // Filter chip + badge

    await tester.tap(find.text('PUBLISHED'));
    await tester.pumpAndSettle();
    expect(find.text('No policies found for this filter.'), findsOneWidget);
  });

  testWidgets('AuthorityPolicyDetailScreen renders draft version and publishes it',
      (tester) async {
    final fakeApi = _FakeAuthorityApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authorityApiServiceProvider.overrideWithValue(fakeApi),
        ],
        child: const MaterialApp(
          home: AuthorityPolicyDetailScreen(policyId: 'pol-draft-1'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Version v1'), findsOneWidget);
    expect(find.text('Preview PDF'), findsOneWidget);
    expect(find.text('Publish'), findsOneWidget);

    await tester.scrollUntilVisible(find.text('Publish'), 200);
    await tester.tap(find.text('Publish'));
    await tester.pumpAndSettle();

    expect(fakeApi.lastPublishedVersionId, 'ver-draft-1');
  });
}


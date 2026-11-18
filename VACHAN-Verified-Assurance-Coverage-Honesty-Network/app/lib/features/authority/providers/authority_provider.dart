import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../auth/models/user_model.dart';
import '../../auth/providers/auth_provider.dart';
import '../../customer/models/claim_model.dart';
import '../models/authority_models.dart';
import '../models/evidence_analysis_model.dart';
import '../services/authority_api_service.dart';

final authorityApiServiceProvider = Provider<AuthorityApiService>((ref) {
  final apiClient = ref.watch(apiClientProvider);
  return AuthorityApiService(apiClient: apiClient);
});

class AuthorityClaimsState {
  final bool isLoading;
  final List<ClaimModel> claims;
  final String? errorMessage;
  final String? statusFilter;
  final String searchQuery;

  const AuthorityClaimsState({
    this.isLoading = false,
    this.claims = const [],
    this.errorMessage,
    this.statusFilter,
    this.searchQuery = '',
  });

  int get submittedCount => claims.where((c) => c.status == 'SUBMITTED').length;
  int get inReviewCount => claims.where((c) => c.status == 'UNDER_REVIEW').length;
  int get evidenceRequestedCount => claims.where((c) => c.status == 'EVIDENCE_REQUESTED').length;
  int get approvedCount => claims.where((c) => c.status == 'APPROVED').length;
  int get paidCount => claims.where((c) => c.status == 'PAID').length;
  int get rejectedCount => claims.where((c) => c.status == 'REJECTED').length;

  List<ClaimModel> get filteredClaims {
    return claims.where((c) {
      final matchesStatus = statusFilter == null || statusFilter == 'ALL' || c.status == statusFilter;
      final matchesQuery = searchQuery.isEmpty ||
          c.id.toLowerCase().contains(searchQuery.toLowerCase()) ||
          c.customerId.toLowerCase().contains(searchQuery.toLowerCase()) ||
          c.claimCategory.toLowerCase().contains(searchQuery.toLowerCase());
      return matchesStatus && matchesQuery;
    }).toList();
  }

  AuthorityClaimsState copyWith({
    bool? isLoading,
    List<ClaimModel>? claims,
    String? errorMessage,
    String? statusFilter,
    String? searchQuery,
  }) {
    return AuthorityClaimsState(
      isLoading: isLoading ?? this.isLoading,
      claims: claims ?? this.claims,
      errorMessage: errorMessage,
      statusFilter: statusFilter ?? this.statusFilter,
      searchQuery: searchQuery ?? this.searchQuery,
    );
  }
}

class AuthorityClaimsNotifier extends StateNotifier<AuthorityClaimsState> {
  final AuthorityApiService _apiService;

  AuthorityClaimsNotifier(this._apiService) : super(const AuthorityClaimsState()) {
    fetchClaims();
  }

  Future<void> fetchClaims({String? status}) async {
    state = state.copyWith(isLoading: true, errorMessage: null, statusFilter: status);
    try {
      // Always fetch complete claims list so dashboard KPI counts remain accurate across filters.
      final claims = await _apiService.listAllClaims();
      state = state.copyWith(isLoading: false, claims: claims);
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
    }
  }

  void setSearchQuery(String query) {
    state = state.copyWith(searchQuery: query);
  }

  void setStatusFilter(String? status) {
    state = state.copyWith(statusFilter: status);
  }
}

final authorityClaimsProvider =
    StateNotifierProvider<AuthorityClaimsNotifier, AuthorityClaimsState>((ref) {
  final apiService = ref.watch(authorityApiServiceProvider);
  return AuthorityClaimsNotifier(apiService);
});

final authorityClaimDetailProvider =
    FutureProvider.family<ClaimModel, String>((ref, claimId) async {
  final apiService = ref.watch(authorityApiServiceProvider);
  return await apiService.getClaimDetails(claimId);
});

final authorityDuplicatesProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>((ref, claimId) async {
  final apiService = ref.watch(authorityApiServiceProvider);
  return await apiService.checkDuplicates(claimId);
});

// ==============================================================================
// Agent Approval State & Provider
// ==============================================================================

class AuthorityAgentsState {
  final bool isLoading;
  final List<UserModel> agents;
  final int total;
  final int page;
  final int pageSize;
  final String statusFilter; // PENDING_APPROVAL, ACTIVE, REJECTED, ALL
  final String? errorMessage;

  const AuthorityAgentsState({
    this.isLoading = false,
    this.agents = const [],
    this.total = 0,
    this.page = 1,
    this.pageSize = 20,
    this.statusFilter = 'PENDING_APPROVAL',
    this.errorMessage,
  });

  bool get hasNextPage => page * pageSize < total;
  bool get hasPrevPage => page > 1;

  AuthorityAgentsState copyWith({
    bool? isLoading,
    List<UserModel>? agents,
    int? total,
    int? page,
    int? pageSize,
    String? statusFilter,
    String? errorMessage,
  }) {
    return AuthorityAgentsState(
      isLoading: isLoading ?? this.isLoading,
      agents: agents ?? this.agents,
      total: total ?? this.total,
      page: page ?? this.page,
      pageSize: pageSize ?? this.pageSize,
      statusFilter: statusFilter ?? this.statusFilter,
      errorMessage: errorMessage,
    );
  }
}

class AuthorityAgentsNotifier extends StateNotifier<AuthorityAgentsState> {
  final AuthorityApiService _apiService;

  AuthorityAgentsNotifier(this._apiService, {bool autoLoad = true})
      : super(const AuthorityAgentsState()) {
    if (autoLoad) {
      fetchAgents();
    }
  }

  Future<void> fetchAgents({String? status, int? page}) async {
    final targetStatus = status ?? state.statusFilter;
    final targetPage = page ?? state.page;
    state = state.copyWith(
      isLoading: true,
      errorMessage: null,
      statusFilter: targetStatus,
      page: targetPage,
    );
    try {
      final res = await _apiService.listAgents(
        status: targetStatus,
        page: targetPage,
        pageSize: state.pageSize,
      );
      state = state.copyWith(
        isLoading: false,
        agents: res.items,
        total: res.total,
        page: res.page,
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
    }
  }

  Future<void> decideAgent({
    required String userId,
    required String status,
    String? reason,
  }) async {
    await _apiService.approveOrRejectAgent(
      userId: userId,
      status: status,
      reason: reason,
    );
    await fetchAgents();
  }
}

final authorityAgentsProvider =
    StateNotifierProvider<AuthorityAgentsNotifier, AuthorityAgentsState>((ref) {
  final apiService = ref.watch(authorityApiServiceProvider);
  return AuthorityAgentsNotifier(apiService);
});

// ==============================================================================
// Policy Management State & Providers
// ==============================================================================

class AuthorityPoliciesState {
  final bool isLoading;
  final List<AuthorityPolicyModel> policies;
  final String filter; // ALL, PUBLISHED, DRAFT
  final String? errorMessage;

  const AuthorityPoliciesState({
    this.isLoading = false,
    this.policies = const [],
    this.filter = 'ALL',
    this.errorMessage,
  });

  List<AuthorityPolicyModel> get filteredPolicies {
    if (filter == 'PUBLISHED') {
      return policies.where((p) => p.hasPublishedVersion).toList();
    }
    if (filter == 'DRAFT') {
      return policies.where((p) => !p.hasPublishedVersion || p.versions.any((v) => !v.isPublished)).toList();
    }
    return policies;
  }

  AuthorityPoliciesState copyWith({
    bool? isLoading,
    List<AuthorityPolicyModel>? policies,
    String? filter,
    String? errorMessage,
  }) {
    return AuthorityPoliciesState(
      isLoading: isLoading ?? this.isLoading,
      policies: policies ?? this.policies,
      filter: filter ?? this.filter,
      errorMessage: errorMessage,
    );
  }
}

class AuthorityPoliciesNotifier extends StateNotifier<AuthorityPoliciesState> {
  final AuthorityApiService _apiService;

  AuthorityPoliciesNotifier(this._apiService, {bool autoLoad = true})
      : super(const AuthorityPoliciesState()) {
    if (autoLoad) {
      fetchPolicies();
    }
  }

  Future<void> fetchPolicies() async {
    state = state.copyWith(isLoading: true, errorMessage: null);
    try {
      final list = await _apiService.listManagePolicies();
      state = state.copyWith(isLoading: false, policies: list);
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
    }
  }

  void setFilter(String filter) {
    state = state.copyWith(filter: filter);
  }
}

final authorityPoliciesProvider =
    StateNotifierProvider<AuthorityPoliciesNotifier, AuthorityPoliciesState>((ref) {
  final apiService = ref.watch(authorityApiServiceProvider);
  return AuthorityPoliciesNotifier(apiService);
});

final authorityPolicyDetailProvider =
    FutureProvider.family<AuthorityPolicyModel, String>((ref, policyId) async {
  final apiService = ref.watch(authorityApiServiceProvider);
  return await apiService.getManagePolicyDetail(policyId);
});

final claimEvidenceAnalysisProvider =
    FutureProvider.family<List<EvidenceAnalysisReport>, String>((ref, claimId) async {
  final apiService = ref.watch(authorityApiServiceProvider);
  return await apiService.getClaimEvidenceAnalysis(claimId);
});

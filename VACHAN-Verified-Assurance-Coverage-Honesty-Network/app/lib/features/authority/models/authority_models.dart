import '../../auth/models/user_model.dart';
import '../../customer/models/customer_policy_model.dart';

class AuthorityAgentPageModel {
  final List<UserModel> items;
  final int total;
  final int page;
  final int pageSize;

  const AuthorityAgentPageModel({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  factory AuthorityAgentPageModel.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'] as List? ?? [];
    return AuthorityAgentPageModel(
      items: rawItems
          .map((e) => UserModel.fromJson(e as Map<String, dynamic>))
          .toList(),
      total: (json['total'] as num?)?.toInt() ?? 0,
      page: (json['page'] as num?)?.toInt() ?? 1,
      pageSize: (json['page_size'] as num?)?.toInt() ?? 20,
    );
  }
}

class AuthorityPolicyModel {
  final String id;
  final String insurerName;
  final String policyName;
  final String policyCode;
  final String category;
  final String description;
  final double coverageLimit;
  final int waitingPeriodDays;
  final int claimFilingWindowDays;
  final bool isActive;
  final PolicyVersionModel? latestVersion;
  final List<PolicyVersionModel> versions;

  const AuthorityPolicyModel({
    required this.id,
    required this.insurerName,
    required this.policyName,
    required this.policyCode,
    required this.category,
    required this.description,
    required this.coverageLimit,
    required this.waitingPeriodDays,
    required this.claimFilingWindowDays,
    required this.isActive,
    this.latestVersion,
    this.versions = const [],
  });

  bool get hasPublishedVersion => versions.any((v) => v.isPublished) || latestVersion != null;

  factory AuthorityPolicyModel.fromJson(Map<String, dynamic> json) {
    final rawVersions = json['versions'] as List? ?? [];
    return AuthorityPolicyModel(
      id: json['id'] as String? ?? '',
      insurerName: json['insurer_name'] as String? ?? '',
      policyName: json['policy_name'] as String? ?? '',
      policyCode: json['policy_code'] as String? ?? '',
      category: json['category'] as String? ?? 'GENERIC',
      description: json['description'] as String? ?? '',
      coverageLimit: (json['coverage_limit'] as num?)?.toDouble() ?? 0.0,
      waitingPeriodDays: (json['waiting_period_days'] as num?)?.toInt() ?? 0,
      claimFilingWindowDays: (json['claim_filing_window_days'] as num?)?.toInt() ?? 30,
      isActive: json['is_active'] as bool? ?? true,
      latestVersion: json['latest_version'] != null
          ? PolicyVersionModel.fromJson(json['latest_version'] as Map<String, dynamic>)
          : null,
      versions: rawVersions
          .map((v) => PolicyVersionModel.fromJson(v as Map<String, dynamic>))
          .toList(),
    );
  }
}


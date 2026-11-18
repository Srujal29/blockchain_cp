import 'dart:typed_data';
import 'package:dio/dio.dart';
import '../../../core/network/api_client.dart';
import '../../auth/models/user_model.dart';
import '../../customer/models/claim_model.dart';
import '../../customer/models/customer_policy_model.dart';
import '../models/authority_models.dart';
import '../models/evidence_analysis_model.dart';

class AuthorityApiService {
  final ApiClient apiClient;

  AuthorityApiService({required this.apiClient});

  // 1. List All System-Wide Claims
  Future<List<ClaimModel>> listAllClaims({
    String? status,
    int page = 1,
    int pageSize = 100,
  }) async {
    try {
      final response = await apiClient.dio.get(
        '/claims',
        queryParameters: {
          if (status != null && status.isNotEmpty && status != 'ALL') 'status': status,
          'page': page,
          'page_size': pageSize,
        },
      );
      final list = (response.data as List)
          .map((item) => ClaimModel.fromJson(item as Map<String, dynamic>))
          .toList();
      return list;
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // 2. Get Claim Details
  Future<ClaimModel> getClaimDetails(String claimId) async {
    try {
      final response = await apiClient.dio.get('/claims/$claimId');
      return ClaimModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // 3. Deterministic Eligibility Assessment Execution
  Future<ClaimAssessmentModel> assessClaim(String claimId) async {
    try {
      final response = await apiClient.dio.post('/claims/$claimId/assess');
      return ClaimAssessmentModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // 4. Duplicate Claims Check
  Future<List<Map<String, dynamic>>> checkDuplicates(String claimId) async {
    try {
      final response = await apiClient.dio.get('/claims/$claimId/duplicates');
      final data = response.data as Map<String, dynamic>;
      final candidates = data['candidates'] as List? ?? [];
      return candidates.map((c) => Map<String, dynamic>.from(c as Map)).toList();
    } catch (e) {
      return [];
    }
  }

  // 5. Short-lived Signed URL for Private Cloudinary Evidence View
  Future<String> getEvidenceSignedUrl(String claimId, String evidenceId) async {
    try {
      final response = await apiClient.dio.get('/claims/$claimId/evidence/$evidenceId/signed-url');
      final data = response.data as Map<String, dynamic>;
      return data['signed_url'] as String? ?? '';
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // 6. Transition Claim Lifecycle Status (Requires reason >= 5 chars)
  Future<ClaimModel> transitionStatus({
    required String claimId,
    required String targetStatus,
    required String reason,
    Map<String, dynamic>? decisionMetadata,
  }) async {
    try {
      final response = await apiClient.dio.post(
        '/claims/$claimId/transition',
        data: {
          'target_status': targetStatus,
          'reason': reason,
          'decision_metadata': decisionMetadata ?? {},
        },
      );
      return ClaimModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // 7. Simulated Payment Execution (Exclusively for APPROVED claims, transitions to PAID)
  Future<ClaimModel> simulatePayment({
    required String claimId,
    required String reason,
    Map<String, dynamic>? decisionMetadata,
  }) async {
    try {
      final response = await apiClient.dio.post(
        '/claims/$claimId/simulate-payment',
        data: {
          'target_status': 'PAID',
          'reason': reason,
          'decision_metadata': decisionMetadata ?? {},
        },
      );
      return ClaimModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // 8. Status History
  Future<List<ClaimStatusHistoryModel>> getStatusHistory(String claimId) async {
    try {
      final response = await apiClient.dio.get('/claims/$claimId/history');
      return (response.data as List)
          .map((item) => ClaimStatusHistoryModel.fromJson(item as Map<String, dynamic>))
          .toList();
    } catch (e) {
      return [];
    }
  }

  // 9. Agent Approval Workflow
  Future<AuthorityAgentPageModel> listAgents({
    String? status,
    int page = 1,
    int pageSize = 20,
  }) async {
    try {
      final response = await apiClient.dio.get(
        '/auth/agents',
        queryParameters: {
          if (status != null && status.isNotEmpty) 'status': status,
          'page': page,
          'page_size': pageSize,
        },
      );
      return AuthorityAgentPageModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<UserModel> approveOrRejectAgent({
    required String userId,
    required String status,
    String? reason,
  }) async {
    try {
      final response = await apiClient.dio.post(
        '/auth/approve-account',
        data: {
          'user_id': userId,
          'status': status,
          if (reason != null && reason.trim().isNotEmpty) 'reason': reason.trim(),
        },
      );
      return UserModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // 10. Policy Management Workflow
  Future<List<AuthorityPolicyModel>> listManagePolicies({String? category}) async {
    try {
      final response = await apiClient.dio.get(
        '/policies/manage',
        queryParameters: {
          if (category != null && category.isNotEmpty) 'category': category,
        },
      );
      final list = response.data as List;
      return list
          .map((item) => AuthorityPolicyModel.fromJson(item as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<AuthorityPolicyModel> getManagePolicyDetail(String policyId) async {
    try {
      final response = await apiClient.dio.get('/policies/$policyId/manage');
      return AuthorityPolicyModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

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
    try {
      final response = await apiClient.dio.post(
        '/policies',
        data: {
          'insurer_name': insurerName,
          'policy_name': policyName,
          'policy_code': policyCode,
          'category': category,
          'description': description,
          'coverage_limit': coverageLimit,
          'waiting_period_days': waitingPeriodDays,
          'claim_filing_window_days': claimFilingWindowDays,
        },
      );
      return AuthorityPolicyModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<PolicyVersionModel> uploadPolicyVersionPdf({
    required String policyId,
    required String effectiveDate,
    String? expiryDate,
    int? versionNumber,
    required String filename,
    required int sizeBytes,
    Stream<List<int>> Function()? streamFactory,
    String? filePath,
    Uint8List? bytes,
    void Function(double progress)? onProgress,
  }) async {
    try {
      final mediaType = DioMediaType.parse('application/pdf');
      final MultipartFile multipartFile;
      if (streamFactory != null) {
        multipartFile = MultipartFile.fromStream(
          streamFactory,
          sizeBytes,
          filename: filename,
          contentType: mediaType,
        );
      } else if (filePath != null && filePath.isNotEmpty) {
        multipartFile = await MultipartFile.fromFile(
          filePath,
          filename: filename,
          contentType: mediaType,
        );
      } else if (bytes != null) {
        multipartFile = MultipartFile.fromBytes(
          bytes,
          filename: filename,
          contentType: mediaType,
        );
      } else {
        throw Exception('No readable PDF stream, path, or bytes available.');
      }

      final formData = FormData.fromMap({
        'effective_date': effectiveDate,
        if (expiryDate != null && expiryDate.isNotEmpty) 'expiry_date': expiryDate,
        if (versionNumber != null) 'version_number': versionNumber.toString(),
        'file': multipartFile,
      });

      final response = await apiClient.dio.post(
        '/policies/$policyId/versions/upload-pdf',
        data: formData,
        onSendProgress: (sent, total) {
          final effTotal = total > 0 ? total : sizeBytes;
          if (effTotal > 0) {
            onProgress?.call((sent / effTotal).clamp(0.0, 1.0));
          }
        },
      );
      return PolicyVersionModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<String> getPolicyVersionDocumentUrl(String policyId, String versionId) async {
    try {
      final response = await apiClient.dio.get(
        '/policies/$policyId/versions/$versionId/document-url',
      );
      return response.data['signed_url'] as String? ?? '';
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<PolicyVersionModel> publishPolicyVersion(String policyId, String versionId) async {
    try {
      final response = await apiClient.dio.post(
        '/policies/$policyId/versions/$versionId/publish',
      );
      return PolicyVersionModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // Phase 6 Evidence Analysis
  Future<List<EvidenceAnalysisReport>> getClaimEvidenceAnalysis(String claimId) async {
    try {
      final response = await apiClient.dio.get('/claims/$claimId/evidence-analysis');
      final list = (response.data['reports'] as List? ?? []);
      return list.map((item) => EvidenceAnalysisReport.fromJson(item as Map<String, dynamic>)).toList();
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<EvidenceAnalysisReport> reanalyzeEvidence(String claimId, String evidenceId) async {
    try {
      final response = await apiClient.dio.post('/claims/$claimId/evidence/$evidenceId/analyze');
      return EvidenceAnalysisReport.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }
}

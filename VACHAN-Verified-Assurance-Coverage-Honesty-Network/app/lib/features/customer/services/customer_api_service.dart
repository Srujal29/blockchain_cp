import 'package:dio/dio.dart';
import '../../../core/network/api_client.dart';
import '../models/claim_model.dart';
import '../models/claim_spoken_explanation_model.dart';
import '../models/customer_policy_model.dart';
import '../models/evidence_upload_item.dart';
import '../models/policy_assistant_model.dart';
import '../models/verification_report_model.dart';
import '../../authority/models/evidence_analysis_model.dart';

class CustomerApiService {
  final ApiClient apiClient;

  CustomerApiService({required this.apiClient});

  // Policies
  Future<List<DetailedPolicyModel>> listPolicies({String? category}) async {
    try {
      final response = await apiClient.dio.get(
        '/policies',
        queryParameters: category != null ? {'category': category} : null,
      );
      final list = (response.data as List)
          .map((item) => DetailedPolicyModel.fromJson(item as Map<String, dynamic>))
          .toList();
      return list;
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<DetailedPolicyModel> getPolicyDetails(String policyId) async {
    try {
      final response = await apiClient.dio.get('/policies/$policyId');
      return DetailedPolicyModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<String> getPublishedPolicyDocumentUrl(String policyId, String versionId) async {
    try {
      final response = await apiClient.dio.get(
        '/policies/$policyId/versions/$versionId/published-document-url',
      );
      final data = response.data as Map<String, dynamic>;
      final signedUrl = data['signed_url'] as String?;
      if (signedUrl == null || signedUrl.isEmpty) {
        throw Exception('No signed document URL returned by server.');
      }
      return signedUrl;
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // Registrations
  Future<List<CustomerRegistrationModel>> listRegistrations({String? status}) async {
    try {
      final response = await apiClient.dio.get(
        '/registrations',
        queryParameters: status != null ? {'status': status} : null,
      );
      final rawList = response.data as List;
      final registrations = <CustomerRegistrationModel>[];
      for (final item in rawList) {
        registrations.add(CustomerRegistrationModel.fromJson(item as Map<String, dynamic>));
      }
      return registrations;
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<CustomerRegistrationModel> getRegistrationDetails(String registrationId) async {
    try {
      final response = await apiClient.dio.get('/registrations/$registrationId');
      return CustomerRegistrationModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<CustomerRegistrationModel> confirmRegistration(String registrationId) async {
    try {
      final response = await apiClient.dio.post('/registrations/$registrationId/confirm');
      return CustomerRegistrationModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<CustomerRegistrationModel> declineRegistration(String registrationId) async {
    try {
      final response = await apiClient.dio.post('/registrations/$registrationId/decline');
      return CustomerRegistrationModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  // Claims
  Future<List<ClaimModel>> listClaims({String? status}) async {
    try {
      final response = await apiClient.dio.get(
        '/claims',
        queryParameters: status != null ? {'status': status} : null,
      );
      return (response.data as List)
          .map((item) => ClaimModel.fromJson(item as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<ClaimModel> getClaimDetails(String claimId) async {
    try {
      final response = await apiClient.dio.get('/claims/$claimId');
      return ClaimModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<ClaimModel> submitClaim({
    required String registrationId,
    required String claimCategory,
    required double requestedAmount,
    required String incidentDate,
    required String description,
    Map<String, dynamic> structuredDetails = const {},
  }) async {
    try {
      final response = await apiClient.dio.post(
        '/claims',
        data: {
          'registration_id': registrationId,
          'claim_category': claimCategory,
          'requested_amount': requestedAmount,
          'incident_date': incidentDate,
          'description': description,
          'structured_details': structuredDetails,
        },
      );
      return ClaimModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<void> uploadClaimEvidenceItem({
    required String claimId,
    required EvidenceUploadItem item,
    void Function(double progress)? onProgress,
  }) async {
    try {
      final mediaType = DioMediaType.parse(item.mimeType);
      final MultipartFile multipartFile;
      if (item.streamFactory != null) {
        multipartFile = MultipartFile.fromStream(
          item.streamFactory!,
          item.sizeBytes,
          filename: item.filename,
          contentType: mediaType,
        );
      } else if (item.filePath != null && item.filePath!.isNotEmpty) {
        multipartFile = await MultipartFile.fromFile(
          item.filePath!,
          filename: item.filename,
          contentType: mediaType,
        );
      } else if (item.bytes != null) {
        multipartFile = MultipartFile.fromBytes(
          item.bytes!,
          filename: item.filename,
          contentType: mediaType,
        );
      } else {
        throw Exception('No readable file stream, path, or bytes available.');
      }

      final formData = FormData.fromMap({
        'evidence_type': item.evidenceType,
        'file': multipartFile,
      });

      await apiClient.dio.post(
        '/claims/$claimId/evidence',
        data: formData,
        onSendProgress: (sent, total) {
          final effectiveTotal = total > 0 ? total : item.sizeBytes;
          if (effectiveTotal > 0) {
            onProgress?.call((sent / effectiveTotal).clamp(0.0, 1.0));
          }
        },
      );
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<String> getEvidenceSignedUrl(String claimId, String evidenceId) async {
    try {
      final response = await apiClient.dio.get(
        '/claims/$claimId/evidence/$evidenceId/signed-url',
      );
      return response.data['signed_url'] as String;
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<void> uploadClaimEvidence({
    required String claimId,
    required String evidenceType,
    required String filename,
    required List<int> bytes,
    required String mimeType,
  }) async {
    try {
      final formData = FormData.fromMap({
        'evidence_type': evidenceType,
        'file': MultipartFile.fromBytes(
          bytes,
          filename: filename,
          contentType: DioMediaType.parse(mimeType),
        ),
      });
      await apiClient.dio.post(
        '/claims/$claimId/evidence',
        data: formData,
      );
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<void> assessClaim(String claimId) async {
    try {
      await apiClient.dio.post('/claims/$claimId/assess');
    } catch (_) {
      // Graceful error ignore
    }
  }

  // Policy Verification Reports
  Future<VerificationReportModel?> getSessionVerification(String sessionId) async {
    try {
      final response = await apiClient.dio.get('/sales-sessions/$sessionId/verification');
      return VerificationReportModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      // 404 or missing report is handled gracefully
      return null;
    }
  }

  Future<VerificationReportModel> getVerificationReport(String reportId) async {
    try {
      final response = await apiClient.dio.get('/verification-reports/$reportId');
      return VerificationReportModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<VerificationReportModel?> getRegistrationVerification(String registrationId) async {
    try {
      final response = await apiClient.dio.get('/registrations/$registrationId/verification');
      return VerificationReportModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      return null;
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

  // Phase 5 Conversational Policy Assistant & Spoken Explainability
  Future<PolicyAssistantResponseModel> queryPolicyAssistant({
    required String question,
    String? policyId,
    bool voiceOutput = true,
  }) async {
    try {
      final response = await apiClient.dio.post(
        '/voice/assistant/query',
        data: {
          'question': question,
          if (policyId != null) 'policy_id': policyId,
          'voice_output': voiceOutput,
        },
      );
      return PolicyAssistantResponseModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<ClaimSpokenExplanationModel> getClaimSpokenExplanation(String claimId) async {
    try {
      final response = await apiClient.dio.post('/claims/$claimId/spoken-explanation');
      return ClaimSpokenExplanationModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }
}


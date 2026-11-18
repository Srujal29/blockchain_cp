class DemoScenarioModel {
  final String scenarioId;
  final String title;
  final String category;
  final String policyName;
  final String description;
  final String inputConditions;
  final String engineEvaluation;
  final String expectedOutcome;
  final String? stage2AnalysisStatus;

  DemoScenarioModel({
    required this.scenarioId,
    required this.title,
    required this.category,
    required this.policyName,
    required this.description,
    required this.inputConditions,
    required this.engineEvaluation,
    required this.expectedOutcome,
    this.stage2AnalysisStatus,
  });

  factory DemoScenarioModel.fromJson(Map<String, dynamic> json) {
    return DemoScenarioModel(
      scenarioId: json['scenario_id'] as String,
      title: json['title'] as String,
      category: json['category'] as String,
      policyName: json['policy_name'] as String,
      description: json['description'] as String,
      inputConditions: json['input_conditions'] as String,
      engineEvaluation: json['engine_evaluation'] as String,
      expectedOutcome: json['expected_outcome'] as String,
      stage2AnalysisStatus: json['stage2_analysis_status'] as String?,
    );
  }
}

class DemoSeedResultModel {
  final String scenarioId;
  final bool seeded;
  final String status;
  final String? claimId;
  final String? sessionId;
  final String? policyId;
  final String? customerEmail;
  final String message;

  DemoSeedResultModel({
    required this.scenarioId,
    required this.seeded,
    required this.status,
    this.claimId,
    this.sessionId,
    this.policyId,
    this.customerEmail,
    required this.message,
  });

  factory DemoSeedResultModel.fromJson(Map<String, dynamic> json) {
    return DemoSeedResultModel(
      scenarioId: json['scenario_id'] as String,
      seeded: json['seeded'] as bool,
      status: json['status'] as String,
      claimId: json['claim_id'] as String?,
      sessionId: json['session_id'] as String?,
      policyId: json['policy_id'] as String?,
      customerEmail: json['customer_email'] as String?,
      message: json['message'] as String,
    );
  }
}

class DemoTamperCheckResultModel {
  final String scenarioId;
  final String authenticRoot;
  final int leafCount;
  final int testedLeafIndex;
  final String testedEventId;
  final bool authenticProofValid;
  final String tamperedLeafHash;
  final bool tamperedProofValid;
  final bool tamperDetected;
  final String verificationExplanation;

  DemoTamperCheckResultModel({
    required this.scenarioId,
    required this.authenticRoot,
    required this.leafCount,
    required this.testedLeafIndex,
    required this.testedEventId,
    required this.authenticProofValid,
    required this.tamperedLeafHash,
    required this.tamperedProofValid,
    required this.tamperDetected,
    required this.verificationExplanation,
  });

  factory DemoTamperCheckResultModel.fromJson(Map<String, dynamic> json) {
    return DemoTamperCheckResultModel(
      scenarioId: json['scenario_id'] as String,
      authenticRoot: json['authentic_root'] as String,
      leafCount: json['leaf_count'] as int,
      testedLeafIndex: json['tested_leaf_index'] as int,
      testedEventId: json['tested_event_id'] as String,
      authenticProofValid: json['authentic_proof_valid'] as bool,
      tamperedLeafHash: json['tampered_leaf_hash'] as String,
      tamperedProofValid: json['tampered_proof_valid'] as bool,
      tamperDetected: json['tamper_detected'] as bool,
      verificationExplanation: json['verification_explanation'] as String,
    );
  }
}

class DemoCleanupResultModel {
  final bool success;
  final Map<String, dynamic> deletedRecords;
  final String message;

  DemoCleanupResultModel({
    required this.success,
    required this.deletedRecords,
    required this.message,
  });

  factory DemoCleanupResultModel.fromJson(Map<String, dynamic> json) {
    return DemoCleanupResultModel(
      success: json['success'] as bool,
      deletedRecords: json['deleted_records'] as Map<String, dynamic>? ?? {},
      message: json['message'] as String,
    );
  }
}


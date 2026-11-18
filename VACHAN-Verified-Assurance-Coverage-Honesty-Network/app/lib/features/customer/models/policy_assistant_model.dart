class PolicyAssistantResponseModel {
  final String question;
  final String answer;
  final String? policyId;
  final String? policyName;
  final List<String> clauseReferences;
  final double confidence;
  final bool isGrounded;
  final String? audioBase64;
  final String audioFormat;
  final double? audioDurationSeconds;
  final String voiceProvider;

  const PolicyAssistantResponseModel({
    required this.question,
    required this.answer,
    this.policyId,
    this.policyName,
    required this.clauseReferences,
    required this.confidence,
    required this.isGrounded,
    this.audioBase64,
    required this.audioFormat,
    this.audioDurationSeconds,
    required this.voiceProvider,
  });

  factory PolicyAssistantResponseModel.fromJson(Map<String, dynamic> json) {
    return PolicyAssistantResponseModel(
      question: json['question'] as String? ?? '',
      answer: json['answer'] as String? ?? '',
      policyId: json['policy_id'] as String?,
      policyName: json['policy_name'] as String?,
      clauseReferences: (json['clause_references'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
      confidence: (json['confidence'] as num?)?.toDouble() ?? 1.0,
      isGrounded: json['is_grounded'] as bool? ?? true,
      audioBase64: json['audio_base64'] as String?,
      audioFormat: json['audio_format'] as String? ?? 'audio/mpeg',
      audioDurationSeconds: (json['audio_duration_seconds'] as num?)?.toDouble(),
      voiceProvider: json['voice_provider'] as String? ?? 'elevenlabs',
    );
  }
}


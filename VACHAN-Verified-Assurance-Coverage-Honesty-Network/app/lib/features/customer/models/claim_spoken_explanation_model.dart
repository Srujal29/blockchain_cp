class ClaimSpokenExplanationModel {
  final String claimId;
  final String claimNumber;
  final String claimStatus;
  final String adjudicationDecision;
  final String recordedReason;
  final String explanationText;
  final String? audioBase64;
  final String audioFormat;
  final String generatedAt;
  final String voiceProvider;

  const ClaimSpokenExplanationModel({
    required this.claimId,
    required this.claimNumber,
    required this.claimStatus,
    required this.adjudicationDecision,
    required this.recordedReason,
    required this.explanationText,
    this.audioBase64,
    required this.audioFormat,
    required this.generatedAt,
    required this.voiceProvider,
  });

  factory ClaimSpokenExplanationModel.fromJson(Map<String, dynamic> json) {
    return ClaimSpokenExplanationModel(
      claimId: json['claim_id'] as String? ?? '',
      claimNumber: json['claim_number'] as String? ?? '',
      claimStatus: json['claim_status'] as String? ?? '',
      adjudicationDecision: json['adjudication_decision'] as String? ?? '',
      recordedReason: json['recorded_reason'] as String? ?? '',
      explanationText: json['explanation_text'] as String? ?? '',
      audioBase64: json['audio_base64'] as String?,
      audioFormat: json['audio_format'] as String? ?? 'audio/mpeg',
      generatedAt: json['generated_at'] as String? ?? '',
      voiceProvider: json['voice_provider'] as String? ?? 'elevenlabs',
    );
  }
}


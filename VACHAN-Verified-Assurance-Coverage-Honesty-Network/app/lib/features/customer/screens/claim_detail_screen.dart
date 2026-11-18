import 'dart:convert';
import 'dart:typed_data';
import 'package:audioplayers/audioplayers.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/glass_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../models/claim_model.dart';
import '../models/claim_spoken_explanation_model.dart';
import '../models/evidence_upload_item.dart';
import '../providers/customer_provider.dart';
import '../../authority/models/evidence_analysis_model.dart';
import '../../authority/widgets/evidence_analysis_card.dart';

final claimDetailFutureProvider =
    FutureProvider.family<ClaimModel, String>((ref, claimId) async {
  final apiService = ref.watch(customerApiServiceProvider);
  return await apiService.getClaimDetails(claimId);
});

class ClaimDetailScreen extends ConsumerWidget {
  final String claimId;

  const ClaimDetailScreen({super.key, required this.claimId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final claimAsync = ref.watch(claimDetailFutureProvider(claimId));

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Claim Evaluation Details'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          onPressed: () => context.pop(),
        ),
      ),
      body: SafeArea(
        child: claimAsync.when(
          loading: () => const Center(
            child: CircularProgressIndicator(
              valueColor: AlwaysStoppedAnimation<Color>(AppTheme.gradientSkyBlue),
            ),
          ),
          error: (err, _) => Center(
            child: Padding(
              padding: const EdgeInsets.all(24.0),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.error_outline_rounded, color: AppTheme.error, size: 40),
                  const SizedBox(height: 14),
                  Text(err.toString(), textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () => ref.refresh(claimDetailFutureProvider(claimId)),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
          data: (claim) => _buildDetailContent(context, ref, claim),
        ),
      ),
    );
  }

  Widget _buildDetailContent(BuildContext context, WidgetRef ref, ClaimModel claim) {
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 12.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header Card
          GlassCard(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: AppTheme.gradientSkyBlue.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        claim.claimCategory,
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.gradientSkyBlue,
                        ),
                      ),
                    ),
                    StatusBadge.fromStatus(claim.status),
                  ],
                ),
                const SizedBox(height: 14),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        'Claim #${claim.id.substring(0, claim.id.length > 8 ? 8 : claim.id.length)}',
                        style: const TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    Text(
                      '\$${claim.requestedAmount}',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.darkTeal,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  'Incident Date: ${claim.incidentDate} • Filed: ${claim.submissionTimestamp.split('T').first}',
                  style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 14),
                const Text(
                  'Incident Description:',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                ),
                const SizedBox(height: 4),
                Text(
                  claim.description,
                  style: const TextStyle(fontSize: 13, color: AppTheme.textPrimary, height: 1.4),
                ),
              ],
            ),
          ),

          const SizedBox(height: 20),

          // Phase 5 Spoken Adjudication Decision Explanation
          if (['APPROVED', 'REJECTED', 'UNDER_REVIEW'].contains(claim.status)) ...[
            _buildSpokenExplanationCard(context, ref, claim),
            const SizedBox(height: 20),
          ],

          // Deterministic Eligibility Assessment
          if (claim.latestAssessment != null) ...[
            _buildAssessmentSection(claim.latestAssessment!),
            const SizedBox(height: 20),
          ],

          // Evidence Section
          _buildEvidenceSection(context, ref, claim),

          const SizedBox(height: 20),

          // Lifecycle History Section
          if (claim.statusHistory.isNotEmpty) ...[
            _buildHistorySection(claim.statusHistory),
            const SizedBox(height: 20),
          ],

          const SizedBox(height: 16),
        ],
      ),
    );
  }

  Widget _buildAssessmentSection(ClaimAssessmentModel assessment) {
    Color outcomeColor;
    String outcomeLabel;
    if (assessment.overallOutcome == 'ELIGIBLE') {
      outcomeColor = AppTheme.success;
      outcomeLabel = 'ELIGIBLE';
    } else if (assessment.overallOutcome == 'NEEDS_REVIEW') {
      outcomeColor = AppTheme.warning;
      outcomeLabel = 'NEEDS REVIEW';
    } else if (assessment.overallOutcome == 'INELIGIBLE') {
      outcomeColor = AppTheme.error;
      outcomeLabel = 'INELIGIBLE';
    } else {
      outcomeColor = AppTheme.textSecondary;
      outcomeLabel = assessment.overallOutcome.replaceAll('_', ' ');
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Automated Eligibility Assessment',
          style: TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w800,
            color: AppTheme.textPrimary,
            letterSpacing: -0.3,
          ),
        ),
        const SizedBox(height: 10),
        GlassCard(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    'Deterministic Outcome',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppTheme.textSecondary),
                  ),
                  StatusBadge(
                    label: outcomeLabel,
                    color: outcomeColor,
                  ),
                ],
              ),
              const Divider(color: AppTheme.borderLight, height: 22),
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Potentially Payable', style: TextStyle(fontSize: 11, color: AppTheme.textSecondary)),
                        const SizedBox(height: 2),
                        Text(
                          '\$${assessment.potentiallyPayableAmount}',
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: AppTheme.success),
                        ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Applicable Limit', style: TextStyle(fontSize: 11, color: AppTheme.textSecondary)),
                        const SizedBox(height: 2),
                        Text(
                          '\$${assessment.applicableLimit}',
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: AppTheme.textPrimary),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              if (assessment.rulesEvaluated.isNotEmpty) ...[
                const SizedBox(height: 16),
                const Text(
                  'Rules Evaluated:',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                ),
                const SizedBox(height: 8),
                ...assessment.rulesEvaluated.map((rule) {
                  final isPass = rule.result == 'PASS';
                  return Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: isPass
                          ? AppTheme.success.withValues(alpha: 0.08)
                          : AppTheme.warning.withValues(alpha: 0.08),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          isPass ? Icons.check_circle_rounded : Icons.info_rounded,
                          size: 16,
                          color: isPass ? AppTheme.success : AppTheme.warning,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            '${rule.ruleId.replaceAll('_', ' ')}: ${rule.explanation}',
                            style: const TextStyle(fontSize: 12, color: AppTheme.textPrimary),
                          ),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Future<void> _openEvidence(
    BuildContext context,
    WidgetRef ref,
    String claimId,
    String evidenceId,
  ) async {
    try {
      final url = await ref
          .read(customerApiServiceProvider)
          .getEvidenceSignedUrl(claimId, evidenceId);
      final uri = Uri.parse(url);
      final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!launched && context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not open evidence document on this device.'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to open evidence: $e'), backgroundColor: AppTheme.error),
        );
      }
    }
  }

  Future<void> _uploadAdditionalEvidence(
    BuildContext context,
    WidgetRef ref,
    ClaimModel claim,
  ) async {
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: EvidenceUploadItem.allowedExtensions.toList(),
      allowMultiple: false,
      withReadStream: true,
      withData: false,
    );
    if (result == null || result.files.isEmpty) return;

    final file = result.files.first;
    final err = EvidenceUploadItem.validateFile(file.name, file.size);
    final mime = EvidenceUploadItem.inferMimeType(file.name);
    if (err != null || mime == null) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(err ?? 'Unsupported file.'), backgroundColor: AppTheme.error),
        );
      }
      return;
    }

    final item = EvidenceUploadItem(
      id: '${DateTime.now().microsecondsSinceEpoch}_${file.name}',
      filename: file.name,
      sizeBytes: file.size,
      mimeType: mime,
      evidenceType: 'SUPPORTING_DOCUMENT',
      filePath: file.path,
      streamFactory: file.readStream != null ? () => file.readStream! : null,
      bytes: file.bytes,
    );

    try {
      await ref.read(claimsListProvider.notifier).uploadEvidenceItem(
            claimId: claim.id,
            item: item,
          );
      ref.invalidate(claimDetailFutureProvider(claim.id));
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Uploaded "${file.name}" securely.'),
            backgroundColor: AppTheme.success,
          ),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Upload failed: $e'), backgroundColor: AppTheme.error),
        );
      }
    }
  }

  Widget _buildEvidenceSection(
    BuildContext context,
    WidgetRef ref,
    ClaimModel claim,
  ) {
    final evidenceList = claim.evidence;
    final canUploadMore = const {
      'SUBMITTED',
      'UNDER_REVIEW',
      'EVIDENCE_REQUESTED',
    }.contains(claim.status) &&
        evidenceList.length < EvidenceUploadItem.maxFilesPerClaim;

    final analysisAsync = ref.watch(customerClaimEvidenceAnalysisProvider(claim.id));
    final analysisReports = analysisAsync.value ?? const <EvidenceAnalysisReport>[];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'Evidence Documents & Verification',
              style: TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w800,
                color: AppTheme.textPrimary,
                letterSpacing: -0.3,
              ),
            ),
            if (canUploadMore)
              TextButton.icon(
                onPressed: () => _uploadAdditionalEvidence(context, ref, claim),
                icon: const Icon(Icons.add_circle_outline_rounded, size: 18),
                label: Text('Add (${evidenceList.length}/5)'),
              ),
          ],
        ),
        const SizedBox(height: 10),
        if (evidenceList.isEmpty) ...[
          const GlassCard(
            padding: EdgeInsets.all(16),
            child: Row(
              children: [
                Icon(Icons.folder_open_rounded, color: AppTheme.textMuted, size: 24),
                SizedBox(width: 12),
                Expanded(
                  child: Text(
                    'No evidence files uploaded yet.',
                    style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                  ),
                ),
              ],
            ),
          ),
        ] else ...[
          ...evidenceList.map((e) {
            final sizeKb = (e.fileSizeBytes / 1024).toStringAsFixed(1);
            final report = analysisReports.where((r) => r.evidenceId == e.id && r.isLatest).firstOrNull;

            return Padding(
              padding: const EdgeInsets.only(bottom: 8.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  GlassCard(
                    padding: const EdgeInsets.all(14),
                    child: Row(
                      children: [
                        const Icon(Icons.attach_file_rounded, color: AppTheme.gradientSkyBlue, size: 22),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                e.originalFilename,
                                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              Text(
                                '$sizeKb KB • ${e.mimeType} • Status: ${e.analysisStatus}',
                                style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                              ),
                            ],
                          ),
                        ),
                        TextButton.icon(
                          onPressed: () => _openEvidence(context, ref, claim.id, e.id),
                          icon: const Icon(Icons.open_in_new_rounded, size: 15),
                          label: const Text('View', style: TextStyle(fontSize: 11)),
                        ),
                      ],
                    ),
                  ),
                  if (report != null)
                    EvidenceAnalysisCard(
                      report: report,
                      onReanalyze: null,
                    ),
                ],
              ),
            );
          }),
        ],
      ],
    );
  }

  Widget _buildHistorySection(List<ClaimStatusHistoryModel> history) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Audit Lifecycle History',
          style: TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w800,
            color: AppTheme.textPrimary,
            letterSpacing: -0.3,
          ),
        ),
        const SizedBox(height: 10),
        GlassCard(
          padding: const EdgeInsets.all(16),
          child: ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: history.length,
            separatorBuilder: (_, __) => const Divider(color: AppTheme.borderLight, height: 16),
            itemBuilder: (context, index) {
              final h = history[index];
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    margin: const EdgeInsets.only(top: 5),
                    decoration: const BoxDecoration(
                      color: AppTheme.gradientSkyBlue,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              h.newStatus,
                              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                            ),
                            Text(
                              h.createdAt.split('T').first,
                              style: const TextStyle(fontSize: 11, color: AppTheme.textMuted),
                            ),
                          ],
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '${h.actorRole}: ${h.reason}',
                          style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                        ),
                      ],
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildSpokenExplanationCard(BuildContext context, WidgetRef ref, ClaimModel claim) {
    final isApproved = claim.status == 'APPROVED';
    final isRejected = claim.status == 'REJECTED';
    final cardColor = isApproved ? const Color(0xFFF0FDF4) : (isRejected ? const Color(0xFFFEF2F2) : const Color(0xFFF0F9FF));
    final borderColor = isApproved ? const Color(0xFFBBF7D0) : (isRejected ? const Color(0xFFFECACA) : const Color(0xFFBAE6FD));
    final iconColor = isApproved ? const Color(0xFF15803D) : (isRejected ? const Color(0xFFB91C1C) : const Color(0xFF0369A1));

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: cardColor,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.record_voice_over_rounded, color: iconColor, size: 22),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  isApproved
                      ? 'Claim Approved • Spoken Explanation Available'
                      : isRejected
                          ? 'Claim Rejected • Spoken Explanation Available'
                          : 'Underwriting Review • Spoken Guidance',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    color: iconColor,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Listen to the transparent, plain-language explanation of the adjudication decision synthesized via ElevenLabs Voice AI.',
            style: TextStyle(fontSize: 12, color: Color(0xFF334155), height: 1.35),
          ),
          const SizedBox(height: 12),
          ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
              backgroundColor: iconColor,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            ),
            icon: const Icon(Icons.play_circle_filled_rounded, size: 18),
            label: const Text('Listen to Decision Explanation', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
            onPressed: () => _openSpokenExplanationSheet(context, ref, claim.id),
          ),
        ],
      ),
    );
  }

  void _openSpokenExplanationSheet(BuildContext context, WidgetRef ref, String claimId) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _SpokenExplanationModal(claimId: claimId),
    );
  }
}

class _SpokenExplanationModal extends ConsumerStatefulWidget {
  final String claimId;

  const _SpokenExplanationModal({required this.claimId});

  @override
  ConsumerState<_SpokenExplanationModal> createState() => _SpokenExplanationModalState();
}

class _SpokenExplanationModalState extends ConsumerState<_SpokenExplanationModal> {
  final AudioPlayer _player = AudioPlayer();
  PlayerState _playerState = PlayerState.stopped;
  ClaimSpokenExplanationModel? _explanation;
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _player.onPlayerStateChanged.listen((state) {
      if (mounted) {
        setState(() => _playerState = state);
      }
    });
    _loadExplanation();
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  Future<void> _loadExplanation() async {
    try {
      final api = ref.read(customerApiServiceProvider);
      final res = await api.getClaimSpokenExplanation(widget.claimId);
      if (mounted) {
        setState(() {
          _explanation = res;
          _isLoading = false;
        });
        if (res.audioBase64 != null && res.audioBase64!.isNotEmpty) {
          _playAudio(res.audioBase64!);
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = e.toString().replaceAll('Exception:', '').trim();
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _playAudio(String audioBase64) async {
    try {
      Uint8List bytes;
      if (audioBase64.contains(',')) {
        bytes = base64Decode(audioBase64.split(',')[1]);
      } else {
        bytes = base64Decode(audioBase64);
      }
      await _player.stop();
      await _player.play(BytesSource(bytes));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Audio playback error: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      padding: const EdgeInsets.all(24),
      constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.75),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey.shade300,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              const Icon(Icons.record_voice_over_rounded, color: AppTheme.darkTeal, size: 24),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  'Spoken Decision Explanation',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: AppTheme.textPrimary),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close_rounded, size: 20),
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (_isLoading)
            const Center(
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: 36),
                child: Column(
                  children: [
                    CircularProgressIndicator(strokeWidth: 2, color: AppTheme.darkTeal),
                    SizedBox(height: 12),
                    Text('Retrieving adjudication reasoning and generating speech...'),
                  ],
                ),
              ),
            )
          else if (_errorMessage != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Column(
                children: [
                  const Icon(Icons.error_outline, color: Colors.red, size: 36),
                  const SizedBox(height: 10),
                  Text(_errorMessage!, textAlign: TextAlign.center, style: const TextStyle(color: Colors.red)),
                ],
              ),
            )
          else if (_explanation != null) ...[
            // Status and Provider Pills
            Row(
              children: [
                StatusBadge.fromStatus(_explanation!.adjudicationDecision),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: AppTheme.darkTeal.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _explanation!.voiceProvider == 'elevenlabs' ? 'ElevenLabs AI' : 'System Audio',
                    style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AppTheme.darkTeal),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            // Audio Playback Controller
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.background,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: AppTheme.darkTeal.withValues(alpha: 0.2)),
              ),
              child: Row(
                children: [
                  IconButton(
                    iconSize: 42,
                    color: AppTheme.darkTeal,
                    icon: Icon(_playerState == PlayerState.playing ? Icons.pause_circle_filled : Icons.play_circle_filled),
                    onPressed: () {
                      if (_playerState == PlayerState.playing) {
                        _player.pause();
                      } else if (_explanation?.audioBase64 != null) {
                        _playAudio(_explanation!.audioBase64!);
                      }
                    },
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _playerState == PlayerState.playing ? 'Playing spoken explanation...' : 'Spoken Audio Ready',
                          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                        ),
                        Text(
                          'Claim: ${_explanation!.claimNumber}',
                          style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'EXPLANATION NARRATIVE',
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: AppTheme.textSecondary, letterSpacing: 0.5),
            ),
            const SizedBox(height: 6),
            Flexible(
              child: SingleChildScrollView(
                child: Text(
                  _explanation!.explanationText,
                  style: const TextStyle(fontSize: 13.5, height: 1.45, color: Color(0xFF1E293B)),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.amber.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.amber.shade200),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.shield_outlined, size: 16, color: Colors.amber.shade900),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Recorded Authority Reason: "${_explanation!.recordedReason}"',
                      style: TextStyle(fontSize: 11, fontStyle: FontStyle.italic, color: Colors.amber.shade900),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

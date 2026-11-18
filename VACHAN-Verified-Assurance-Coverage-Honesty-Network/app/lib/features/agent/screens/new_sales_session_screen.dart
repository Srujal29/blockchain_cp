import 'dart:async';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/glass_card.dart';
import '../providers/agent_provider.dart';

class NewSalesSessionScreen extends ConsumerStatefulWidget {
  const NewSalesSessionScreen({super.key});

  @override
  ConsumerState<NewSalesSessionScreen> createState() => _NewSalesSessionScreenState();
}

class _NewSalesSessionScreenState extends ConsumerState<NewSalesSessionScreen> {
  final _customerIdController = TextEditingController();
  final _customerNameController = TextEditingController();
  final _customerEmailController = TextEditingController();
  final _customerPhoneController = TextEditingController();
  final _consentNotesController = TextEditingController();

  String? _selectedPolicyId;
  String? _selectedRegistrationId;

  // Consent state
  bool _hasAffirmativeConsent = false;

  // Recording state
  late final AudioRecorder _audioRecorder;
  bool _isRecording = false;
  int _recordedSeconds = 0;
  Timer? _timer;
  String? _recordedFilePath;
  int _fileSizeBytes = 0;
  String? _sha256Checksum;

  bool _isSubmitting = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _audioRecorder = AudioRecorder();
    Future.microtask(() {
      ref.invalidate(agentPoliciesProvider);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _audioRecorder.dispose();
    _customerIdController.dispose();
    _customerNameController.dispose();
    _customerEmailController.dispose();
    _customerPhoneController.dispose();
    _consentNotesController.dispose();
    super.dispose();
  }

  Future<void> _startRecording() async {
    if (!_hasAffirmativeConsent) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Affirmative customer consent is mandatory before starting recording.'),
          backgroundColor: AppTheme.error,
        ),
      );
      return;
    }

    try {
      final hasPermission = await _audioRecorder.hasPermission();
      if (!hasPermission) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Microphone permission denied. Please grant microphone access to record.'),
              backgroundColor: AppTheme.error,
            ),
          );
        }
        return;
      }

      final tempDir = await getTemporaryDirectory();
      final path = '${tempDir.path}/sales_session_${DateTime.now().millisecondsSinceEpoch}.m4a';

      await _audioRecorder.start(
        const RecordConfig(encoder: AudioEncoder.aacLc, bitRate: 128000),
        path: path,
      );

      setState(() {
        _isRecording = true;
        _recordedSeconds = 0;
        _recordedFilePath = null;
        _errorMessage = null;
      });

      _timer?.cancel();
      _timer = Timer.periodic(const Duration(seconds: 1), (t) {
        if (mounted) {
          setState(() => _recordedSeconds = t.tick);
        }
      });
    } catch (e) {
      setState(() => _errorMessage = 'Failed to start recording: $e');
    }
  }

  Future<void> _stopRecording() async {
    try {
      _timer?.cancel();
      final path = await _audioRecorder.stop();

      if (path != null) {
        final file = File(path);
        final bytes = await file.readAsBytes();
        final digest = sha256.convert(bytes);

        setState(() {
          _isRecording = false;
          _recordedFilePath = path;
          _fileSizeBytes = bytes.length;
          _sha256Checksum = digest.toString();
        });
      } else {
        setState(() => _isRecording = false);
      }
    } catch (e) {
      setState(() {
        _isRecording = false;
        _errorMessage = 'Error stopping recording: $e';
      });
    }
  }

  Future<void> _cancelRecording() async {
    _timer?.cancel();
    await _audioRecorder.cancel();
    if (_recordedFilePath != null) {
      try {
        final f = File(_recordedFilePath!);
        if (await f.exists()) await f.delete();
      } catch (_) {}
    }
    setState(() {
      _isRecording = false;
      _recordedSeconds = 0;
      _recordedFilePath = null;
      _fileSizeBytes = 0;
      _sha256Checksum = null;
    });
  }

  Future<void> _submitSalesSession() async {
    final customerEmail = _customerEmailController.text.trim();
    final customerName = _customerNameController.text.trim();
    final customerPhone = _customerPhoneController.text.trim();

    if (!_hasAffirmativeConsent) {
      setState(() => _errorMessage = 'Mandatory customer consent must be explicitly confirmed.');
      return;
    }

    if (_sha256Checksum == null || _fileSizeBytes == 0 || _recordedFilePath == null) {
      setState(() => _errorMessage = 'Please complete the voice recording before creating session.');
      return;
    }

    // Backend max audio limit: 25MB (26214400 bytes)
    if (_fileSizeBytes > 26214400) {
      setState(() => _errorMessage = 'Audio size exceeds 25MB limit. Please re-record a shorter clip.');
      return;
    }

    final policies = ref.read(agentPoliciesProvider).valueOrNull ?? [];
    final effectivePolicyId = _selectedPolicyId ?? (policies.isNotEmpty ? policies.first.id : null);
    if (effectivePolicyId == null || effectivePolicyId.isEmpty) {
      setState(() => _errorMessage = 'Please select a published policy before creating a session.');
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final apiService = ref.read(agentApiServiceProvider);
      final session = await apiService.createSalesSession(
        customerId: _customerIdController.text.trim().isNotEmpty ? _customerIdController.text.trim() : null,
        customerEmail: customerEmail.isNotEmpty ? customerEmail : 'customer@insurechain.io',
        customerFullName: customerName.isNotEmpty ? customerName : 'Valued Customer',
        customerPhone: customerPhone.isNotEmpty ? customerPhone : null,
        policyId: effectivePolicyId,
        registrationId: _selectedRegistrationId,
        audioStorageRef: 'voiceguard/sessions/${DateTime.now().millisecondsSinceEpoch}_sales.m4a',
        audioMimeType: 'audio/m4a',
        audioFileSizeBytes: _fileSizeBytes,
        durationSeconds: _recordedSeconds,
        audioChecksum: _sha256Checksum!,
        customerConsent: _hasAffirmativeConsent,
        consentNotes: _consentNotesController.text.trim().isNotEmpty
            ? _consentNotesController.text.trim()
            : 'Affirmative verbal consent recorded during sales conversation.',
      );

      // Upload actual live recorded audio bytes from phone
      if (_recordedFilePath != null && File(_recordedFilePath!).existsSync()) {
        await apiService.uploadSessionAudio(session.id, _recordedFilePath!);
      }

      // Refresh agent sessions list
      ref.read(salesSessionsListProvider.notifier).fetchSessions();

      if (mounted) {
        final registeredEmail = customerEmail.isNotEmpty ? customerEmail : 'customer@insurechain.io';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Session created with live audio for $registeredEmail!'),
            backgroundColor: AppTheme.success,
            duration: const Duration(seconds: 4),
          ),
        );
        context.pushReplacement('/agent/session/${session.id}');
      }
    } catch (e) {
      setState(() {
        _isSubmitting = false;
        _errorMessage = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final policiesAsync = ref.watch(agentPoliciesProvider);

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('New Sales Session'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          onPressed: () => context.pop(),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 12.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_errorMessage != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  margin: const EdgeInsets.only(bottom: 16),
                  decoration: BoxDecoration(
                    color: AppTheme.error.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: AppTheme.error.withValues(alpha: 0.3)),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline_rounded, color: AppTheme.error, size: 20),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          _errorMessage!,
                          style: const TextStyle(fontSize: 12, color: AppTheme.error),
                        ),
                      ),
                    ],
                  ),
                ),
              ],

              // 1. Target Insurance Policy Scheme
              const Text(
                '1. Target Insurance Policy',
                style: TextStyle(
                  fontSize: 16,
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
                    const Text(
                      'Policy Scheme Being Discussed *',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
                    ),
                    const SizedBox(height: 8),
                    policiesAsync.when(
                      data: (policiesList) {
                        if (policiesList.isEmpty) {
                          return Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: AppTheme.warning.withValues(alpha: 0.1),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: AppTheme.warning.withValues(alpha: 0.3)),
                            ),
                            child: const Text(
                              'No published policies available. Ask an Approval Authority to publish a policy before starting a sales session.',
                              style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                            ),
                          );
                        }
                        final uniquePolicies = {for (var p in policiesList) p.id: p}.values.toList();
                        final validIds = uniquePolicies.map((p) => p.id).toSet();
                        final effectivePolicyId = (validIds.contains(_selectedPolicyId))
                            ? _selectedPolicyId!
                            : uniquePolicies.first.id;
                        if (_selectedPolicyId != effectivePolicyId) {
                          WidgetsBinding.instance.addPostFrameCallback((_) {
                            if (mounted && _selectedPolicyId != effectivePolicyId) {
                              setState(() => _selectedPolicyId = effectivePolicyId);
                            }
                          });
                        }

                        return DropdownButtonFormField<String>(
                          key: ValueKey(effectivePolicyId),
                          isExpanded: true,
                          initialValue: effectivePolicyId,
                          decoration: const InputDecoration(
                            filled: true,
                            fillColor: Colors.white,
                            contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                            border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                          ),
                          hint: const Text('Select policy being discussed', style: TextStyle(fontSize: 13)),
                          items: uniquePolicies.map((p) {
                            return DropdownMenuItem(
                              value: p.id,
                              child: Text(
                                '${p.policyName} (${p.category})',
                                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppTheme.textPrimary),
                              ),
                            );
                          }).toList(),
                          onChanged: (val) => setState(() => _selectedPolicyId = val),
                        );
                      },
                      loading: () => const Padding(
                        padding: EdgeInsets.symmetric(vertical: 12),
                        child: LinearProgressIndicator(),
                      ),
                      error: (err, _) => Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: AppTheme.error.withValues(alpha: 0.08),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: AppTheme.error.withValues(alpha: 0.3)),
                        ),
                        child: Row(
                          children: [
                            const Expanded(
                              child: Text(
                                'Failed to load published policies.',
                                style: TextStyle(fontSize: 12, color: AppTheme.error),
                              ),
                            ),
                            TextButton(
                              onPressed: () => ref.invalidate(agentPoliciesProvider),
                              child: const Text('Retry'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 20),

              // 2. Customer Details & Auto-Registration
              const Text(
                '2. Customer Details & Auto-Registration',
                style: TextStyle(
                  fontSize: 16,
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
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AppTheme.gradientSkyBlue.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: AppTheme.gradientSkyBlue.withValues(alpha: 0.2)),
                      ),
                      child: const Row(
                        children: [
                          Icon(Icons.person_add_alt_1_rounded, color: AppTheme.darkTeal, size: 20),
                          SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              'Auto-Registration: An account is generated for this email. Customer logs in using password "password123" to compare promises with underwritten terms and confirm/decline coverage.',
                              style: TextStyle(fontSize: 11, color: Color(0xFF132A33), height: 1.35),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 14),

                    const Text(
                      'Customer Full Name',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _customerNameController,
                      decoration: const InputDecoration(
                        hintText: 'e.g. Rajesh Kumar',
                        filled: true,
                        fillColor: Colors.white,
                        prefixIcon: Icon(Icons.badge_outlined, size: 20, color: AppTheme.textMuted),
                        contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                        border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                      ),
                    ),
                    const SizedBox(height: 12),

                    const Text(
                      'Customer Email Address *',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _customerEmailController,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(
                        hintText: 'e.g. customer@insurechain.io',
                        filled: true,
                        fillColor: Colors.white,
                        prefixIcon: Icon(Icons.email_outlined, size: 20, color: AppTheme.textMuted),
                        contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                        border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                      ),
                    ),
                    const SizedBox(height: 12),

                    const Text(
                      'Customer Phone (Optional)',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _customerPhoneController,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(
                        hintText: 'e.g. +91 98765 43210',
                        filled: true,
                        fillColor: Colors.white,
                        prefixIcon: Icon(Icons.phone_outlined, size: 20, color: AppTheme.textMuted),
                        contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                        border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 20),

              // 3. Affirmative Customer Consent Notice
              const Text(
                '3. Mandatory Customer Recording Consent',
                style: TextStyle(
                  fontSize: 16,
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
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: AppTheme.darkTeal.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: AppTheme.darkTeal.withValues(alpha: 0.15)),
                      ),
                      child: const Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Icon(Icons.gavel_rounded, color: AppTheme.darkTeal, size: 20),
                          SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              'VoiceGuard Statutory Disclosure: '
                              '"This conversation is being recorded with your affirmative consent for transparency and policy promise verification. Verbatim sales statements will be compared against official policy clauses."',
                              style: TextStyle(
                                fontSize: 11,
                                color: Color(0xFF132A33),
                                height: 1.4,
                                fontStyle: FontStyle.italic,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 14),

                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      value: _hasAffirmativeConsent,
                      activeColor: AppTheme.darkTeal,
                      title: const Text(
                        'I confirm customer gave affirmative explicit consent to voice recording.',
                        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                      ),
                      subtitle: const Text(
                        'Mandatory requirement enforced by backend before transcription.',
                        style: TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                      ),
                      onChanged: (val) {
                        setState(() => _hasAffirmativeConsent = val ?? false);
                      },
                    ),

                    const SizedBox(height: 10),

                    const Text(
                      'Consent Notes (Optional):',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _consentNotesController,
                      maxLines: 2,
                      decoration: const InputDecoration(
                        hintText: 'e.g. Customer stated "Yes, I agree to be recorded" at start of call.',
                        filled: true,
                        fillColor: Colors.white,
                        border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: AppTheme.borderLight)),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 20),

              // 4. Audio Recording Controller
              const Text(
                '4. Voice Session Recording',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textPrimary,
                  letterSpacing: -0.3,
                ),
              ),
              const SizedBox(height: 10),

              GlassCard(
                padding: const EdgeInsets.all(22),
                child: Column(
                  children: [
                    // Timer & Status Icon
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        if (_isRecording) ...[
                          Container(
                            width: 12,
                            height: 12,
                            decoration: const BoxDecoration(
                              color: AppTheme.error,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 10),
                        ],
                        Text(
                          _formatDuration(_recordedSeconds),
                          style: TextStyle(
                            fontSize: 32,
                            fontWeight: FontWeight.w900,
                            color: _isRecording ? AppTheme.error : AppTheme.textPrimary,
                            letterSpacing: 1.0,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _isRecording
                          ? 'Recording sales audio with explicit consent...'
                          : _recordedFilePath != null
                              ? 'Recording captured (${(_fileSizeBytes / 1024).toStringAsFixed(1)} KB)'
                              : 'Ready to record conversation',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: _isRecording ? AppTheme.error : AppTheme.textSecondary,
                      ),
                    ),

                    if (_sha256Checksum != null) ...[
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                        decoration: BoxDecoration(
                          color: AppTheme.backgroundSurface,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          'SHA-256: ${_sha256Checksum!.substring(0, 24)}...',
                          style: const TextStyle(fontSize: 10, fontFamily: 'monospace', color: AppTheme.textMuted),
                        ),
                      ),
                    ],

                    const SizedBox(height: 20),

                    // Controls
                    if (_isRecording) ...[
                      Row(
                        children: [
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: _cancelRecording,
                              icon: const Icon(Icons.close_rounded, color: AppTheme.error, size: 18),
                              label: const Text(
                                'Cancel',
                                style: TextStyle(color: AppTheme.error, fontSize: 13, fontWeight: FontWeight.w700),
                                overflow: TextOverflow.ellipsis,
                              ),
                              style: OutlinedButton.styleFrom(
                                side: const BorderSide(color: AppTheme.error),
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: ElevatedButton.icon(
                              onPressed: _stopRecording,
                              icon: const Icon(Icons.stop_rounded, size: 18),
                              label: const Text(
                                'Stop Recording',
                                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                                overflow: TextOverflow.ellipsis,
                              ),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: AppTheme.error,
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ] else ...[
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: _hasAffirmativeConsent ? _startRecording : null,
                          icon: Icon(_recordedFilePath != null ? Icons.replay_rounded : Icons.mic_rounded, size: 20),
                          label: Text(
                            _recordedFilePath != null ? 'Re-Record Audio' : 'Start Recording',
                            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
                          ),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _hasAffirmativeConsent ? AppTheme.darkTeal : AppTheme.textMuted,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 14),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),

              const SizedBox(height: 28),

              // Final Submit Button
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: (_isSubmitting ||
                          _isRecording ||
                          _sha256Checksum == null ||
                          (policiesAsync.valueOrNull ?? []).isEmpty)
                      ? null
                      : _submitSalesSession,
                  icon: _isSubmitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2),
                        )
                      : const Icon(Icons.cloud_upload_rounded),
                  label: Text(
                    _isSubmitting ? 'Creating & Verifying...' : 'Submit Session to VoiceGuard',
                    style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.darkTeal,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
                  ),
                ),
              ),

              const SizedBox(height: 36),
            ],
          ),
        ),
      ),
    );
  }

  String _formatDuration(int seconds) {
    final m = seconds ~/ 60;
    final s = seconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }
}

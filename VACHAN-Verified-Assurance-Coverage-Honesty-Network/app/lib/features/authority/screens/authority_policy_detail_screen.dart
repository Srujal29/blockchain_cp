import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/glass_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../models/authority_models.dart';
import '../providers/authority_provider.dart';

class AuthorityPolicyDetailScreen extends ConsumerStatefulWidget {
  final String policyId;

  const AuthorityPolicyDetailScreen({super.key, required this.policyId});

  @override
  ConsumerState<AuthorityPolicyDetailScreen> createState() =>
      _AuthorityPolicyDetailScreenState();
}

class _AuthorityPolicyDetailScreenState
    extends ConsumerState<AuthorityPolicyDetailScreen> {
  DateTime _effectiveDate = DateTime.now();
  DateTime? _expiryDate;
  PlatformFile? _selectedPdf;
  bool _isUploading = false;
  double _uploadProgress = 0.0;
  bool _isPublishing = false;

  String _formatDate(DateTime dt) =>
      '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';

  Future<void> _pickPdf() async {
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
      allowMultiple: false,
      withReadStream: true,
      withData: false,
    );
    if (result == null || result.files.isEmpty) return;
    final f = result.files.first;
    if (f.size <= 0 || f.size > 10 * 1024 * 1024) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Policy PDF must be between 1 byte and 10 MB.'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
      return;
    }
    setState(() => _selectedPdf = f);
  }

  Future<void> _uploadVersionPdf() async {
    if (_selectedPdf == null) return;
    if (_expiryDate != null && !_expiryDate!.isAfter(_effectiveDate)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Expiry date must be after effective date.'),
          backgroundColor: AppTheme.error,
        ),
      );
      return;
    }

    setState(() {
      _isUploading = true;
      _uploadProgress = 0.0;
    });

    try {
      final f = _selectedPdf!;
      await ref.read(authorityApiServiceProvider).uploadPolicyVersionPdf(
            policyId: widget.policyId,
            effectiveDate: _formatDate(_effectiveDate),
            expiryDate: _expiryDate != null ? _formatDate(_expiryDate!) : null,
            filename: f.name,
            sizeBytes: f.size,
            streamFactory: f.readStream != null ? () => f.readStream! : null,
            filePath: f.path,
            bytes: f.bytes,
            onProgress: (p) {
              if (mounted) setState(() => _uploadProgress = p);
            },
          );

      ref.invalidate(authorityPolicyDetailProvider(widget.policyId));
      ref.read(authorityPoliciesProvider.notifier).fetchPolicies();

      if (mounted) {
        setState(() {
          _selectedPdf = null;
          _isUploading = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('New draft policy version uploaded privately.'),
            backgroundColor: AppTheme.success,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isUploading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Upload failed: $e'), backgroundColor: AppTheme.error),
        );
      }
    }
  }

  Future<void> _previewVersionPdf(String versionId) async {
    try {
      final url = await ref
          .read(authorityApiServiceProvider)
          .getPolicyVersionDocumentUrl(widget.policyId, versionId);
      await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Preview failed: $e'), backgroundColor: AppTheme.error),
        );
      }
    }
  }

  Future<void> _publishVersion(String versionId, int versionNumber) async {
    setState(() => _isPublishing = true);
    try {
      await ref
          .read(authorityApiServiceProvider)
          .publishPolicyVersion(widget.policyId, versionId);
      ref.invalidate(authorityPolicyDetailProvider(widget.policyId));
      ref.read(authorityPoliciesProvider.notifier).fetchPolicies();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Version v$versionNumber published to catalogue.'),
            backgroundColor: AppTheme.success,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Publish failed: $e'), backgroundColor: AppTheme.error),
        );
      }
    } finally {
      if (mounted) setState(() => _isPublishing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final detailAsync = ref.watch(authorityPolicyDetailProvider(widget.policyId));

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Policy Versions & PDF'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            onPressed: () => ref.invalidate(authorityPolicyDetailProvider(widget.policyId)),
          ),
        ],
      ),
      body: SafeArea(
        child: detailAsync.when(
          skipLoadingOnRefresh: true,
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (err, _) => Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(err.toString(), textAlign: TextAlign.center),
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: () => ref.invalidate(authorityPolicyDetailProvider(widget.policyId)),
                  child: const Text('Retry'),
                ),
              ],
            ),
          ),
          data: (policy) => _buildContent(policy),
        ),
      ),
    );
  }

  Widget _buildContent(AuthorityPolicyModel policy) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GlassCard(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        policy.policyName,
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                      ),
                    ),
                    StatusBadge(
                      label: policy.hasPublishedVersion ? 'PUBLISHED' : 'DRAFT',
                      color: policy.hasPublishedVersion ? AppTheme.success : AppTheme.warning,
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  '${policy.policyCode} • ${policy.category} • ${policy.insurerName}',
                  style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 8),
                Text(policy.description, style: const TextStyle(fontSize: 12)),
              ],
            ),
          ),
          const SizedBox(height: 20),
          const Text(
            'Upload New Policy Version PDF',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          GlassCard(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () async {
                          final picked = await showDatePicker(
                            context: context,
                            initialDate: _effectiveDate,
                            firstDate: DateTime(2020),
                            lastDate: DateTime(2035),
                          );
                          if (picked != null) setState(() => _effectiveDate = picked);
                        },
                        icon: const Icon(Icons.calendar_today_rounded, size: 16),
                        label: Text('Effective: ${_formatDate(_effectiveDate)}', style: const TextStyle(fontSize: 11)),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () async {
                          final picked = await showDatePicker(
                            context: context,
                            initialDate: _expiryDate ?? _effectiveDate.add(const Duration(days: 365)),
                            firstDate: DateTime(2020),
                            lastDate: DateTime(2040),
                          );
                          if (picked != null) setState(() => _expiryDate = picked);
                        },
                        icon: const Icon(Icons.event_rounded, size: 16),
                        label: Text(
                          _expiryDate != null ? 'Expiry: ${_formatDate(_expiryDate!)}' : 'Expiry (Optional)',
                          style: const TextStyle(fontSize: 11),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: _isUploading ? null : _pickPdf,
                  icon: const Icon(Icons.picture_as_pdf_rounded),
                  label: Text(_selectedPdf != null ? _selectedPdf!.name : 'Select Policy PDF (max 10 MB)'),
                ),
                if (_isUploading) ...[
                  const SizedBox(height: 10),
                  LinearProgressIndicator(value: _uploadProgress > 0 ? _uploadProgress : null),
                ],
                const SizedBox(height: 12),
                AppButton(
                  label: 'Upload Draft Version',
                  isLoading: _isUploading,
                  onPressed: _selectedPdf == null ? null : _uploadVersionPdf,
                  variant: AppButtonVariant.primaryGradient,
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          Text(
            'Policy Versions (${policy.versions.length})',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          if (policy.versions.isEmpty)
            const GlassCard(
              padding: EdgeInsets.all(16),
              child: Text('No versions uploaded yet. Upload a PDF above to create v1.'),
            )
          else
            ...policy.versions.map((v) {
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: GlassCard(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            'Version v${v.versionNumber}',
                            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800),
                          ),
                          StatusBadge(
                            label: v.isPublished ? 'PUBLISHED' : 'DRAFT',
                            color: v.isPublished ? AppTheme.success : AppTheme.warning,
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Effective: ${v.effectiveDate} • Checksum: ${(v.documentChecksum ?? '').length > 12 ? (v.documentChecksum ?? '').substring(0, 12) : (v.documentChecksum ?? '')}...',
                        style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          OutlinedButton.icon(
                            onPressed: () => _previewVersionPdf(v.id),
                            icon: const Icon(Icons.open_in_new_rounded, size: 15),
                            label: const Text('Preview PDF', style: TextStyle(fontSize: 12)),
                          ),
                          if (!v.isPublished) ...[
                            const SizedBox(width: 10),
                            ElevatedButton.icon(
                              onPressed: _isPublishing ? null : () => _publishVersion(v.id, v.versionNumber),
                              icon: const Icon(Icons.publish_rounded, size: 15),
                              label: const Text('Publish', style: TextStyle(fontSize: 12)),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: AppTheme.success,
                                foregroundColor: Colors.white,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
              );
            }),
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/glass_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../models/customer_policy_model.dart';
import '../providers/customer_provider.dart';

final policyDetailFutureProvider =
    FutureProvider.family<DetailedPolicyModel, String>((ref, policyId) async {
  final apiService = ref.watch(customerApiServiceProvider);
  return await apiService.getPolicyDetails(policyId);
});

class PolicyDetailScreen extends ConsumerStatefulWidget {
  final String policyId;
  final Future<bool> Function(Uri url, {LaunchMode? mode})? onLaunchUrl;

  const PolicyDetailScreen({super.key, required this.policyId, this.onLaunchUrl});

  @override
  ConsumerState<PolicyDetailScreen> createState() => _PolicyDetailScreenState();
}

class _PolicyDetailScreenState extends ConsumerState<PolicyDetailScreen> {
  bool _isLoadingPdf = false;
  String? _pdfErrorMessage;

  Future<void> _viewPolicyPdf(String policyId, String versionId) async {
    setState(() {
      _isLoadingPdf = true;
      _pdfErrorMessage = null;
    });

    try {
      final apiService = ref.read(customerApiServiceProvider);
      final signedUrl = await apiService.getPublishedPolicyDocumentUrl(policyId, versionId);
      final uri = Uri.parse(signedUrl);

      final launcher = widget.onLaunchUrl ?? launchUrl;
      final launched = await launcher(uri, mode: LaunchMode.externalApplication);
      if (!launched) {
        throw Exception('Could not open document viewer for the signed URL.');
      }
    } catch (e) {
      final message = e.toString().replaceFirst('Exception: ', '');
      if (mounted) {
        setState(() {
          _pdfErrorMessage = message;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Document access failed: $message'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isLoadingPdf = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final policyAsync = ref.watch(policyDetailFutureProvider(widget.policyId));

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Policy Specifications'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          onPressed: () => context.pop(),
        ),
      ),
      body: SafeArea(
        child: policyAsync.when(
          loading: () => const Center(
            child: CircularProgressIndicator(
              valueColor: AlwaysStoppedAnimation<Color>(AppTheme.gradientSkyBlue),
            ),
          ),
          error: (err, stack) => Center(
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
                    onPressed: () => ref.refresh(policyDetailFutureProvider(widget.policyId)),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
          data: (policy) => _buildPolicyDetailContent(context, policy),
        ),
      ),
    );
  }

  Widget _buildPolicyDetailContent(BuildContext context, DetailedPolicyModel policy) {
    final version = policy.latestVersion;
    final dashboardState = ref.watch(customerDashboardProvider);
    final matchingReg = dashboardState.registrations.cast<CustomerRegistrationModel?>().firstWhere(
      (r) => r?.policyId == policy.id,
      orElse: () => null,
    );

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
                        policy.category,
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.gradientSkyBlue,
                        ),
                      ),
                    ),
                    StatusBadge(
                      label: policy.isActive ? 'Active Scheme' : 'Inactive',
                      color: policy.isActive ? AppTheme.success : AppTheme.error,
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  policy.policyName,
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                    letterSpacing: -0.3,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  'Policy Code: ${policy.policyCode} • Underwritten by ${policy.insurerName}',
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppTheme.textSecondary,
                  ),
                ),
                if (policy.description != null && policy.description!.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(
                    policy.description!,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppTheme.textPrimary,
                      height: 1.4,
                    ),
                  ),
                ],
              ],
            ),
          ),

          if (matchingReg != null) ...[
            const SizedBox(height: 16),
            GlassCard(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: AppTheme.darkTeal.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: const Icon(Icons.compare_arrows_rounded, color: AppTheme.darkTeal, size: 20),
                      ),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Sales Pitch vs Policy Verification',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w800,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                            SizedBox(height: 2),
                            Text(
                              'Gemini compared agent statements against verified PDF clauses',
                              style: TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: () async {
                        showDialog(
                          context: context,
                          barrierDismissible: false,
                          builder: (_) => const Center(
                            child: CircularProgressIndicator(color: AppTheme.darkTeal),
                          ),
                        );
                        try {
                          final apiService = ref.read(customerApiServiceProvider);
                          final report = await apiService.getRegistrationVerification(matchingReg.id);
                          if (context.mounted) Navigator.of(context, rootNavigator: true).pop();
                          if (report != null && context.mounted) {
                            context.push('/verification-report/${report.id}');
                          } else if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('No AI verification report found yet.')),
                            );
                          }
                        } catch (e) {
                          if (context.mounted) Navigator.of(context, rootNavigator: true).pop();
                        }
                      },
                      icon: const Icon(Icons.analytics_outlined, size: 16),
                      label: const Text('Compare Transcript & Policy Terms', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.darkTeal,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        padding: const EdgeInsets.symmetric(vertical: 10),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],

          const SizedBox(height: 16),

          // Underwriting Parameters Grid
          Row(
            children: [
              Expanded(
                child: _buildParameterTile(
                  icon: Icons.attach_money_rounded,
                  label: 'Coverage Limit',
                  value: '\$${policy.coverageLimit.toStringAsFixed(0)}',
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildParameterTile(
                  icon: Icons.hourglass_bottom_rounded,
                  label: 'Waiting Period',
                  value: '${policy.waitingPeriodDays} Days',
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _buildParameterTile(
            icon: Icons.calendar_month_rounded,
            label: 'Claim Filing Window',
            value: '${policy.claimFilingWindowDays} days from incident occurrence',
          ),

          const SizedBox(height: 20),

          // Published Version Terms Section
          if (version != null) ...[
            const Text(
              'Published Policy Version',
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
                      Text(
                        'Version #${version.versionNumber}',
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppTheme.success.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Text(
                          'Verified Underwriting Document',
                          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AppTheme.success),
                        ),
                      ),
                    ],
                  ),
                  if (version.documentChecksum != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      'Document SHA-256 Checksum: ${version.documentChecksum}',
                      style: const TextStyle(fontSize: 11, color: AppTheme.textMuted),
                    ),
                  ],
                  if (version.effectiveDate != null) ...[
                    const SizedBox(height: 6),
                    Text(
                      'Effective: ${version.effectiveDate} ${version.expiryDate != null ? 'to ${version.expiryDate}' : ''}',
                      style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                    ),
                  ],
                  if (version.termsJson.isNotEmpty) ...[
                    const Divider(color: AppTheme.borderLight, height: 24),
                    const Text(
                      'Key Underwritten Clauses:',
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                    ),
                    const SizedBox(height: 8),
                    ...version.termsJson.entries.map((entry) {
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('• ', style: TextStyle(fontWeight: FontWeight.bold)),
                            Expanded(
                              child: Text(
                                '${entry.key.replaceAll('_', ' ')}: ${entry.value}',
                                style: const TextStyle(fontSize: 12, color: AppTheme.textPrimary),
                              ),
                            ),
                          ],
                        ),
                      );
                    }),
                  ],
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      key: const Key('view_policy_pdf_button'),
                      onPressed: _isLoadingPdf ? null : () => _viewPolicyPdf(policy.id, version.id),
                      icon: _isLoadingPdf
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : const Icon(Icons.picture_as_pdf_rounded, size: 18),
                      label: Text(
                        _isLoadingPdf ? 'Requesting Secure Document...' : 'View Policy PDF',
                        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.gradientSkyBlue,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                  if (_pdfErrorMessage != null) ...[
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        const Icon(Icons.error_outline_rounded, size: 14, color: AppTheme.error),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            _pdfErrorMessage!,
                            style: const TextStyle(fontSize: 11, color: AppTheme.error),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],

          const SizedBox(height: 20),

          // Blockchain Audit Seal
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppTheme.darkTeal.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppTheme.darkTeal.withValues(alpha: 0.15)),
            ),
            child: const Row(
              children: [
                Icon(Icons.link_rounded, color: AppTheme.darkTeal, size: 24),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Blockchain Integrity Protected',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.darkTeal,
                        ),
                      ),
                      SizedBox(height: 2),
                      Text(
                        'Policy version hash and terms root are anchored on-chain to prevent unannounced clause alterations.',
                        style: TextStyle(
                          fontSize: 11,
                          color: Color(0xFF2C5561),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: 28),
        ],
      ),
    );
  }

  Widget _buildParameterTile({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return GlassCard(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      borderRadius: 18,
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppTheme.gradientSkyBlue.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, color: AppTheme.gradientSkyBlue, size: 18),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

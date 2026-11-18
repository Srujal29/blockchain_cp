import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/glass_card.dart';
import '../models/demo_scenario_model.dart';
import '../providers/demo_provider.dart';

class DemoScenariosScreen extends ConsumerStatefulWidget {
  const DemoScenariosScreen({super.key});

  @override
  ConsumerState<DemoScenariosScreen> createState() => _DemoScenariosScreenState();
}

class _DemoScenariosScreenState extends ConsumerState<DemoScenariosScreen> {
  String _selectedCategory = 'ALL';
  final Map<String, DemoSeedResultModel> _seededScenarios = {};

  @override
  Widget build(BuildContext context) {
    final scenariosAsync = ref.watch(demoScenariosProvider);
    final demoState = ref.watch(demoNotifierProvider);

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Demo Scenarios (Phase 6)'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Reload Scenarios',
            onPressed: () => ref.refresh(demoScenariosProvider),
          ),
          IconButton(
            icon: const Icon(Icons.delete_sweep_rounded, color: AppTheme.error),
            tooltip: 'Purge Demo Data',
            onPressed: demoState.isLoading ? null : () => _showCleanupConfirmation(context),
          ),
        ],
      ),
      body: SafeArea(
        child: scenariosAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (err, stack) => Center(
            child: Padding(
              padding: const EdgeInsets.all(24.0),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.error_outline_rounded, size: 48, color: AppTheme.error),
                  const SizedBox(height: 12),
                  Text('Failed to load demo scenarios: $err', textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () => ref.refresh(demoScenariosProvider),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
          data: (scenarios) {
            final filtered = _selectedCategory == 'ALL'
                ? scenarios
                : scenarios.where((s) => s.category.toUpperCase() == _selectedCategory).toList();

            return SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildHeaderBanner(context, demoState),
                  const SizedBox(height: 14),
                  _buildFilterChips(),
                  const SizedBox(height: 14),
                  ...filtered.map((s) => _buildScenarioCard(context, s, demoState)),
                  const SizedBox(height: 24),
                ],
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildHeaderBanner(BuildContext context, DemoState demoState) {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  gradient: AppTheme.primaryGradient,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Text(
                  '15 WORKFLOW SCENARIOS',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: Colors.white),
                ),
              ),
              const Spacer(),
              if (demoState.isLoading)
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
          const SizedBox(height: 10),
          const Text(
            'Deterministic Policy & Evidence Demonstrator',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: AppTheme.textPrimary),
          ),
          const SizedBox(height: 4),
          const Text(
            'Explore end-to-end insurance workflows: multimodal OCR invoice auditing, sales mis-selling verification, rule engine assessments, and cryptographic Merkle integrity.',
            style: TextStyle(fontSize: 12, color: AppTheme.textSecondary, height: 1.3),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: demoState.isLoading
                      ? null
                      : () async {
                          final results = await ref.read(demoNotifierProvider.notifier).seedAll();
                          if (results != null && context.mounted) {
                            setState(() {
                              for (final r in results) {
                                _seededScenarios[r.scenarioId] = r;
                              }
                            });
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('Seeded ${results.length} scenarios successfully!')),
                            );
                          }
                        },
                  icon: const Icon(Icons.playlist_add_check_rounded, size: 16),
                  label: const Text('Seed All Scenarios'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.darkTeal,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: demoState.isLoading ? null : () => _showCleanupConfirmation(context),
                icon: const Icon(Icons.delete_outline_rounded, size: 16, color: AppTheme.error),
                label: const Text('Purge Demo', style: TextStyle(color: AppTheme.error)),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: AppTheme.error),
                  padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildFilterChips() {
    final categories = ['ALL', 'VEHICLE', 'MEDICAL', 'GOVERNANCE'];
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: categories.map((cat) {
          final isSelected = _selectedCategory == cat;
          return Padding(
            padding: const EdgeInsets.only(right: 8.0),
            child: ChoiceChip(
              label: Text(
                cat,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: isSelected ? Colors.white : AppTheme.textSecondary,
                ),
              ),
              selected: isSelected,
              selectedColor: AppTheme.darkTeal,
              backgroundColor: AppTheme.cardWhite,
              onSelected: (val) {
                if (val) setState(() => _selectedCategory = cat);
              },
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildScenarioCard(BuildContext context, DemoScenarioModel scn, DemoState demoState) {
    final isCurrentLoading = demoState.isLoading && demoState.activeScenarioId == scn.scenarioId;
    final seedResult = _seededScenarios[scn.scenarioId] ??
        (demoState.lastSeedResult?.scenarioId == scn.scenarioId ? demoState.lastSeedResult : null);

    Color outcomeColor;
    if (scn.expectedOutcome.startsWith('ELIGIBLE')) {
      outcomeColor = AppTheme.success;
    } else if (scn.expectedOutcome.startsWith('INELIGIBLE')) {
      outcomeColor = AppTheme.error;
    } else if (scn.expectedOutcome.startsWith('NEEDS_REVIEW')) {
      outcomeColor = AppTheme.warning;
    } else {
      outcomeColor = Colors.purple;
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 12.0),
      child: GlassCard(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: AppTheme.darkTeal.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    scn.scenarioId,
                    style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.darkTeal,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.blueGrey.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    scn.category,
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Colors.blueGrey),
                  ),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: outcomeColor.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    scn.expectedOutcome.split(' ')[0],
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: outcomeColor),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              scn.title,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: AppTheme.textPrimary),
            ),
            const SizedBox(height: 2),
            Text(
              scn.policyName,
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AppTheme.gradientSkyBlue),
            ),
            const SizedBox(height: 6),
            Text(
              scn.description,
              style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary, height: 1.3),
            ),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppTheme.background,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Conditions: ${scn.inputConditions}',
                    style: const TextStyle(fontSize: 11, color: AppTheme.textPrimary),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Evaluation: ${scn.engineEvaluation}',
                    style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                  ),
                  if (scn.stage2AnalysisStatus != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      'OCR / Invoice Auditor: ${scn.stage2AnalysisStatus}',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: scn.stage2AnalysisStatus!.contains('DISCREPANCIES')
                            ? AppTheme.warning
                            : scn.stage2AnalysisStatus!.contains('NEEDS_MANUAL')
                                ? AppTheme.error
                                : AppTheme.success,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                ElevatedButton.icon(
                  onPressed: isCurrentLoading ? null : () => _runScenario(context, scn),
                  icon: isCurrentLoading
                      ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.play_arrow_rounded, size: 16),
                  label: Text(scn.scenarioId == 'DEMO-SCN-15' ? 'Verify Cryptographic Merkle' : 'Seed / Run'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.darkTeal,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                ),
                const SizedBox(width: 10),
                if (seedResult?.claimId != null || seedResult?.sessionId != null)
                  OutlinedButton.icon(
                    onPressed: () => _inspectScenarioRecord(context, scn, seedResult!),
                    icon: const Icon(Icons.visibility_rounded, size: 16),
                    label: const Text('Inspect Record'),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _runScenario(BuildContext context, DemoScenarioModel scn) async {
    if (scn.scenarioId == 'DEMO-SCN-15') {
      final res = await ref.read(demoNotifierProvider.notifier).runTamperCheck();
      if (res != null && context.mounted) {
        _showTamperDialog(context, res);
      }
      return;
    }

    final res = await ref.read(demoNotifierProvider.notifier).seedScenario(scn.scenarioId);
    if (res != null && context.mounted) {
      setState(() => _seededScenarios[scn.scenarioId] = res);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${scn.scenarioId}: ${res.message}')),
      );
    }
  }

  void _inspectScenarioRecord(
    BuildContext context,
    DemoScenarioModel scn,
    DemoSeedResultModel result,
  ) {
    if (result.claimId != null) {
      context.push('/claims/claim-detail', extra: {'claimId': result.claimId});
    } else if (result.sessionId != null) {
      context.push('/agent/sales-sessions/detail', extra: {'sessionId': result.sessionId});
    }
  }

  void _showTamperDialog(BuildContext context, DemoTamperCheckResultModel res) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Scenario 15: Merkle Audit Verification'),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppTheme.success.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.check_circle_rounded, color: AppTheme.success, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Authentic Proof: Valid (${res.authenticProofValid})',
                        style: const TextStyle(fontWeight: FontWeight.w700, color: AppTheme.success, fontSize: 13),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppTheme.error.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.gpp_bad_rounded, color: AppTheme.error, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Tampered Payload: Rejected (${!res.tamperedProofValid})',
                        style: const TextStyle(fontWeight: FontWeight.w700, color: AppTheme.error, fontSize: 13),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Text(
                'Merkle Root:\n${res.authenticRoot}',
                style: const TextStyle(fontSize: 10, fontFamily: 'monospace', color: AppTheme.textSecondary),
              ),
              const SizedBox(height: 8),
              Text(
                'Tampered Leaf Hash:\n${res.tamperedLeafHash}',
                style: const TextStyle(fontSize: 10, fontFamily: 'monospace', color: AppTheme.error),
              ),
              const SizedBox(height: 12),
              Text(
                res.verificationExplanation,
                style: const TextStyle(fontSize: 12, color: AppTheme.textPrimary, height: 1.3),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Close'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              context.push('/integrity');
            },
            child: const Text('View Blockchain Integrity'),
          ),
        ],
      ),
    );
  }

  void _showCleanupConfirmation(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Purge Demonstration Records?'),
        content: const Text(
          'This will permanently delete all demonstration claims, evidence analysis reports, demo sales sessions, and demo accounts.\n\n'
          'Existing non-demo customer, policy, and audit records will not be touched.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.of(ctx).pop();
              final res = await ref.read(demoNotifierProvider.notifier).cleanup();
              if (res != null && context.mounted) {
                setState(() => _seededScenarios.clear());
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(res.message)),
                );
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.error),
            child: const Text('Purge Demo Data'),
          ),
        ],
      ),
    );
  }
}

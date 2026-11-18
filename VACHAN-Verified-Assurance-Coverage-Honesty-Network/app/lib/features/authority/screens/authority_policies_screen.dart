import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_text_field.dart';
import '../../../shared/widgets/glass_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../providers/authority_provider.dart';

class AuthorityPoliciesScreen extends ConsumerWidget {
  const AuthorityPoliciesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(authorityPoliciesProvider);
    final policies = state.filteredPolicies;
    final filters = ['ALL', 'PUBLISHED', 'DRAFT'];

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Policy Management'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            onPressed: () => ref.read(authorityPoliciesProvider.notifier).fetchPolicies(),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: AppTheme.darkTeal,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add_rounded),
        label: const Text('Create Policy'),
        onPressed: () => context.push('/authority/policies/create'),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(
                children: filters.map((f) {
                  final selected = state.filter == f;
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(f, style: const TextStyle(fontSize: 12)),
                      selected: selected,
                      selectedColor: AppTheme.darkTeal,
                      labelStyle: TextStyle(color: selected ? Colors.white : AppTheme.textPrimary),
                      onSelected: (_) => ref.read(authorityPoliciesProvider.notifier).setFilter(f),
                    ),
                  );
                }).toList(),
              ),
            ),
            Expanded(
              child: state.isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : state.errorMessage != null
                      ? Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(state.errorMessage!, textAlign: TextAlign.center),
                              const SizedBox(height: 12),
                              ElevatedButton(
                                onPressed: () => ref.read(authorityPoliciesProvider.notifier).fetchPolicies(),
                                child: const Text('Retry'),
                              ),
                            ],
                          ),
                        )
                      : policies.isEmpty
                          ? const Center(
                              child: Text('No policies found for this filter.', style: TextStyle(color: AppTheme.textSecondary)),
                            )
                          : ListView.separated(
                              padding: const EdgeInsets.fromLTRB(16, 4, 16, 88),
                              itemCount: policies.length,
                              separatorBuilder: (_, __) => const SizedBox(height: 10),
                              itemBuilder: (context, index) {
                                final p = policies[index];
                                final statusLabel = p.hasPublishedVersion ? 'PUBLISHED' : 'DRAFT';
                                return GlassCard(
                                  padding: const EdgeInsets.all(16),
                                  onTap: () => context.push('/authority/policies/${p.id}'),
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                        children: [
                                          Expanded(
                                            child: Text(
                                              p.policyName,
                                              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
                                            ),
                                          ),
                                          StatusBadge(
                                            label: statusLabel,
                                            color: p.hasPublishedVersion ? AppTheme.success : AppTheme.warning,
                                          ),
                                        ],
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        '${p.policyCode} • ${p.category} • ${p.insurerName}',
                                        style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                                      ),
                                      const SizedBox(height: 6),
                                      Text(
                                        '${p.versions.length} version(s) • Coverage: ₹${p.coverageLimit.toStringAsFixed(0)}',
                                        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AppTheme.darkTeal),
                                      ),
                                    ],
                                  ),
                                );
                              },
                            ),
            ),
          ],
        ),
      ),
    );
  }
}

class AuthorityCreatePolicyScreen extends ConsumerStatefulWidget {
  const AuthorityCreatePolicyScreen({super.key});

  @override
  ConsumerState<AuthorityCreatePolicyScreen> createState() => _AuthorityCreatePolicyScreenState();
}

class _AuthorityCreatePolicyScreenState extends ConsumerState<AuthorityCreatePolicyScreen> {
  final _formKey = GlobalKey<FormState>();
  final _insurerController = TextEditingController();
  final _nameController = TextEditingController();
  final _codeController = TextEditingController();
  final _descController = TextEditingController();
  final _limitController = TextEditingController(text: '500000');
  final _waitingController = TextEditingController(text: '30');
  final _windowController = TextEditingController(text: '30');

  String _category = 'HOSPITALIZATION';
  bool _isSubmitting = false;

  @override
  void dispose() {
    _insurerController.dispose();
    _nameController.dispose();
    _codeController.dispose();
    _descController.dispose();
    _limitController.dispose();
    _waitingController.dispose();
    _windowController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final limit = double.tryParse(_limitController.text.trim());
    final waiting = int.tryParse(_waitingController.text.trim()) ?? 0;
    final window = int.tryParse(_windowController.text.trim()) ?? 30;
    if (limit == null || limit <= 0 || window <= 0 || waiting < 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Enter valid positive numeric underwriting limits.'), backgroundColor: AppTheme.error),
      );
      return;
    }

    setState(() => _isSubmitting = true);
    try {
      final created = await ref.read(authorityApiServiceProvider).createPolicy(
            insurerName: _insurerController.text.trim(),
            policyName: _nameController.text.trim(),
            policyCode: _codeController.text.trim().toUpperCase(),
            category: _category,
            description: _descController.text.trim(),
            coverageLimit: limit,
            waitingPeriodDays: waiting,
            claimFilingWindowDays: window,
          );
      ref.read(authorityPoliciesProvider.notifier).fetchPolicies();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Policy ${created.policyCode} created as DRAFT.'), backgroundColor: AppTheme.success),
        );
        context.pushReplacement('/authority/policies/${created.id}');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to create policy: $e'), backgroundColor: AppTheme.error),
        );
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(title: const Text('Create Policy')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                AppTextField(
                  controller: _insurerController,
                  labelText: 'Insurer Name *',
                  hintText: 'e.g. Care Premier Health',
                  validator: (v) => (v == null || v.trim().length < 2) ? 'Min 2 characters' : null,
                ),
                const SizedBox(height: 12),
                AppTextField(
                  controller: _nameController,
                  labelText: 'Policy Name *',
                  hintText: 'e.g. Care Premier Shield',
                  validator: (v) => (v == null || v.trim().length < 2) ? 'Min 2 characters' : null,
                ),
                const SizedBox(height: 12),
                AppTextField(
                  controller: _codeController,
                  labelText: 'Policy Code *',
                  hintText: 'e.g. VG-MED-101',
                  validator: (v) => (v == null || v.trim().length < 3) ? 'Min 3 characters' : null,
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _category,
                  decoration: const InputDecoration(
                    labelText: 'Category *',
                    border: OutlineInputBorder(),
                    filled: true,
                    fillColor: Colors.white,
                  ),
                  items: const [
                    DropdownMenuItem(value: 'HOSPITALIZATION', child: Text('HOSPITALIZATION')),
                    DropdownMenuItem(value: 'MEDICAL', child: Text('MEDICAL')),
                    DropdownMenuItem(value: 'VEHICLE', child: Text('VEHICLE')),
                    DropdownMenuItem(value: 'GENERIC', child: Text('GENERIC')),
                  ],
                  onChanged: (v) {
                    if (v != null) setState(() => _category = v);
                  },
                ),
                const SizedBox(height: 12),
                AppTextField(
                  controller: _descController,
                  labelText: 'Description *',
                  hintText: 'Underwriting coverage summary (min 10 chars)',
                  maxLines: 3,
                  validator: (v) => (v == null || v.trim().length < 10) ? 'Min 10 characters' : null,
                ),
                const SizedBox(height: 12),
                AppTextField(
                  controller: _limitController,
                  labelText: 'Coverage Limit *',
                  hintText: 'e.g. 500000',
                  keyboardType: TextInputType.number,
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: AppTextField(
                        controller: _waitingController,
                        labelText: 'Waiting Period (days)',
                        hintText: 'e.g. 30',
                        keyboardType: TextInputType.number,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: AppTextField(
                        controller: _windowController,
                        labelText: 'Filing Window (days)',
                        hintText: 'e.g. 30',
                        keyboardType: TextInputType.number,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                AppButton(
                  label: 'Create Draft Policy',
                  isLoading: _isSubmitting,
                  onPressed: _submit,
                  variant: AppButtonVariant.primaryGradient,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

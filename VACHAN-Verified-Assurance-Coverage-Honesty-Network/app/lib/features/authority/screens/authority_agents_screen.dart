import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/glass_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../../auth/models/user_model.dart';
import '../providers/authority_provider.dart';

class AuthorityAgentsScreen extends ConsumerStatefulWidget {
  const AuthorityAgentsScreen({super.key});

  @override
  ConsumerState<AuthorityAgentsScreen> createState() => _AuthorityAgentsScreenState();
}

class _AuthorityAgentsScreenState extends ConsumerState<AuthorityAgentsScreen> {
  bool _isActing = false;

  Future<void> _approveAgent(UserModel agent) async {
    setState(() => _isActing = true);
    try {
      await ref.read(authorityAgentsProvider.notifier).decideAgent(
            userId: agent.id,
            status: 'ACTIVE',
          );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${agent.fullName} approved and activated.'),
            backgroundColor: AppTheme.success,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Approval failed: $e'), backgroundColor: AppTheme.error),
        );
      }
    } finally {
      if (mounted) setState(() => _isActing = false);
    }
  }

  Future<void> _showRejectDialog(UserModel agent) async {
    final confirmedReason = await showDialog<String>(
      context: context,
      builder: (ctx) => _RejectReasonDialog(agentName: agent.fullName),
    );
    if (confirmedReason == null) return;

    setState(() => _isActing = true);
    try {
      await ref.read(authorityAgentsProvider.notifier).decideAgent(
            userId: agent.id,
            status: 'REJECTED',
            reason: confirmedReason,
          );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${agent.fullName} rejected and sessions revoked.'),
            backgroundColor: AppTheme.warning,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Rejection failed: $e'), backgroundColor: AppTheme.error),
        );
      }
    } finally {
      if (mounted) setState(() => _isActing = false);
    }
  }

  void _openAgentDetailSheet(UserModel agent) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) {
        return Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text(
                      agent.fullName,
                      style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                    ),
                  ),
                  StatusBadge.fromStatus(agent.accountStatus.value),
                ],
              ),
              const SizedBox(height: 12),
              _detailRow('Email', agent.email),
              if (agent.phone != null && agent.phone!.isNotEmpty)
                _detailRow('Phone', agent.phone!),
              _detailRow('Role', agent.role.displayName),
              _detailRow('User ID', agent.id),
              const SizedBox(height: 20),
              if (agent.accountStatus != AccountStatus.active) ...[
                Row(
                  children: [
                    if (agent.accountStatus != AccountStatus.rejected)
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _isActing
                              ? null
                              : () {
                                  Navigator.pop(ctx);
                                  _showRejectDialog(agent);
                                },
                          icon: const Icon(Icons.cancel_outlined, color: AppTheme.error),
                          label: const Text('Reject', style: TextStyle(color: AppTheme.error)),
                          style: OutlinedButton.styleFrom(
                            side: const BorderSide(color: AppTheme.error),
                            padding: const EdgeInsets.symmetric(vertical: 12),
                          ),
                        ),
                      ),
                    if (agent.accountStatus != AccountStatus.rejected)
                      const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton.icon(
                        onPressed: _isActing
                            ? null
                            : () {
                                Navigator.pop(ctx);
                                _approveAgent(agent);
                              },
                        icon: const Icon(Icons.check_circle_outline_rounded),
                        label: const Text('Approve Agent'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.success,
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                      ),
                    ),
                  ],
                ),
              ] else ...[
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _isActing
                        ? null
                        : () {
                            Navigator.pop(ctx);
                            _showRejectDialog(agent);
                          },
                    icon: const Icon(Icons.block_rounded, color: AppTheme.error),
                    label: const Text('Revoke & Reject Agent', style: TextStyle(color: AppTheme.error)),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: AppTheme.error),
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _detailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary)),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.end,
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final agentsState = ref.watch(authorityAgentsProvider);
    final filters = ['PENDING_APPROVAL', 'ACTIVE', 'REJECTED', 'ALL'];

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Agent Approvals'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            onPressed: () => ref.read(authorityAgentsProvider.notifier).fetchAgents(),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(
                children: filters.map((f) {
                  final selected = agentsState.statusFilter == f;
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(f.replaceAll('_', ' '), style: const TextStyle(fontSize: 12)),
                      selected: selected,
                      selectedColor: AppTheme.darkTeal,
                      labelStyle: TextStyle(color: selected ? Colors.white : AppTheme.textPrimary),
                      onSelected: (_) {
                        ref.read(authorityAgentsProvider.notifier).fetchAgents(status: f, page: 1);
                      },
                    ),
                  );
                }).toList(),
              ),
            ),
            if (_isActing) const LinearProgressIndicator(),
            Expanded(
              child: agentsState.isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : agentsState.errorMessage != null
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(Icons.error_outline_rounded, color: AppTheme.error, size: 36),
                                const SizedBox(height: 8),
                                Text(agentsState.errorMessage!, textAlign: TextAlign.center),
                                const SizedBox(height: 12),
                                ElevatedButton(
                                  onPressed: () => ref.read(authorityAgentsProvider.notifier).fetchAgents(),
                                  child: const Text('Retry'),
                                ),
                              ],
                            ),
                          ),
                        )
                      : agentsState.agents.isEmpty
                          ? Center(
                              child: Text(
                                'No agents found for ${agentsState.statusFilter.replaceAll('_', ' ')}.',
                                style: const TextStyle(color: AppTheme.textSecondary),
                              ),
                            )
                          : ListView.separated(
                              padding: const EdgeInsets.all(16),
                              itemCount: agentsState.agents.length,
                              separatorBuilder: (_, __) => const SizedBox(height: 10),
                              itemBuilder: (context, index) {
                                final agent = agentsState.agents[index];
                                return GlassCard(
                                  padding: const EdgeInsets.all(16),
                                  onTap: () => _openAgentDetailSheet(agent),
                                  child: Row(
                                    children: [
                                      CircleAvatar(
                                        backgroundColor: AppTheme.darkTeal.withValues(alpha: 0.12),
                                        child: const Icon(Icons.person_outline_rounded, color: AppTheme.darkTeal),
                                      ),
                                      const SizedBox(width: 12),
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment: CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              agent.fullName,
                                              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800),
                                            ),
                                            const SizedBox(height: 2),
                                            Text(
                                              agent.email,
                                              style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                                            ),
                                          ],
                                        ),
                                      ),
                                      StatusBadge.fromStatus(agent.accountStatus.value),
                                    ],
                                  ),
                                );
                              },
                            ),
            ),
            if (agentsState.total > agentsState.pageSize)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    TextButton(
                      onPressed: agentsState.hasPrevPage
                          ? () => ref.read(authorityAgentsProvider.notifier).fetchAgents(page: agentsState.page - 1)
                          : null,
                      child: const Text('Previous'),
                    ),
                    Text('Page ${agentsState.page} (${agentsState.total} total)', style: const TextStyle(fontSize: 12)),
                    TextButton(
                      onPressed: agentsState.hasNextPage
                          ? () => ref.read(authorityAgentsProvider.notifier).fetchAgents(page: agentsState.page + 1)
                          : null,
                      child: const Text('Next'),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _RejectReasonDialog extends StatefulWidget {
  final String agentName;
  const _RejectReasonDialog({required this.agentName});

  @override
  State<_RejectReasonDialog> createState() => _RejectReasonDialogState();
}

class _RejectReasonDialogState extends State<_RejectReasonDialog> {
  final _reasonController = TextEditingController();
  String? _validationError;

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Reject ${widget.agentName}'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'A statutory rejection reason (minimum 5 characters) is mandatory. Existing sessions will be revoked.',
            style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _reasonController,
            maxLines: 3,
            decoration: InputDecoration(
              labelText: 'Rejection Reason *',
              hintText: 'e.g. Invalid IRDAI license credentials',
              errorText: _validationError,
              border: const OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: AppTheme.error),
          onPressed: () {
            final text = _reasonController.text.trim();
            if (text.length < 5) {
              setState(() {
                _validationError = 'Reason must be at least 5 characters.';
              });
              return;
            }
            Navigator.pop(context, text);
          },
          child: const Text('Confirm Reject', style: TextStyle(color: Colors.white)),
        ),
      ],
    );
  }
}

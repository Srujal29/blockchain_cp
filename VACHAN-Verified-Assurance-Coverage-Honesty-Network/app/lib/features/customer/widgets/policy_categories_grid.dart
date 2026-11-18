import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/glass_card.dart';
import '../models/customer_policy_model.dart';

class PolicyCategoriesGrid extends StatelessWidget {
  final List<DetailedPolicyModel> policies;
  final ValueChanged<String>? onCategorySelected;
  final VoidCallback? onViewAll;

  const PolicyCategoriesGrid({
    super.key,
    required this.policies,
    this.onCategorySelected,
    this.onViewAll,
  });

  List<DetailedPolicyModel> _getPoliciesForCategory(String categoryKey) {
    final key = categoryKey.toUpperCase();
    List<DetailedPolicyModel> rawList = [];

    if (key == 'MOTOR') {
      rawList = policies
          .where((p) =>
              p.category.toUpperCase().contains('VEHICLE') ||
              p.category.toUpperCase().contains('MOTOR'))
          .toList();
    } else if (key == 'HEALTH') {
      rawList = policies
          .where((p) =>
              p.category.toUpperCase().contains('HOSPITAL') ||
              p.category.toUpperCase().contains('MEDICAL') ||
              p.category.toUpperCase().contains('HEALTH'))
          .toList();
    } else if (key == 'TRAVEL') {
      rawList = policies
          .where((p) =>
              p.category.toUpperCase().contains('TRAVEL') ||
              p.category.toUpperCase().contains('TRIP'))
          .toList();
    } else if (key == 'LIFE') {
      rawList = policies
          .where((p) =>
              p.category.toUpperCase().contains('GENERIC') ||
              p.category.toUpperCase().contains('LIFE') ||
              p.category.toUpperCase().contains('TERM'))
          .toList();
    } else {
      rawList = policies.where((p) => p.category.toUpperCase().contains(key)).toList();
    }

    // Deduplicate by policy name so user sees a clean, distinct list
    final seen = <String>{};
    final distinct = <DetailedPolicyModel>[];
    for (final p in rawList) {
      final nameKey = p.policyName.trim().toLowerCase();
      if (!seen.contains(nameKey)) {
        seen.add(nameKey);
        distinct.add(p);
      }
    }
    return distinct;
  }

  void _showCategoryPoliciesModal(
    BuildContext context, {
    required String categoryKey,
    required String title,
    required IconData icon,
    required Color iconColor,
  }) {
    final matchingPolicies = _getPoliciesForCategory(categoryKey);

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (ctx) {
        return DraggableScrollableSheet(
          initialChildSize: 0.65,
          minChildSize: 0.4,
          maxChildSize: 0.9,
          expand: false,
          builder: (_, scrollController) {
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
              child: ListView(
                controller: scrollController,
                children: [
                  Center(
                    child: Container(
                      width: 44,
                      height: 5,
                      decoration: BoxDecoration(
                        color: Colors.grey.shade300,
                        borderRadius: BorderRadius.circular(3),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: iconColor.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Icon(icon, color: iconColor, size: 24),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              title,
                              style: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                            Text(
                              '${matchingPolicies.length} available plan(s) in catalogue',
                              style: const TextStyle(
                                fontSize: 12,
                                color: AppTheme.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  if (matchingPolicies.isEmpty) ...[
                    Container(
                      padding: const EdgeInsets.all(24),
                      decoration: BoxDecoration(
                        color: AppTheme.backgroundSurface,
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(color: AppTheme.borderLight),
                      ),
                      child: Column(
                        children: [
                          const Icon(Icons.inventory_2_outlined,
                              size: 44, color: AppTheme.textMuted),
                          const SizedBox(height: 12),
                          Text(
                            'Featured $title Coming Soon',
                            style: const TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 6),
                          const Text(
                            'New underwriting plans for this category are being certified on the blockchain.',
                            textAlign: TextAlign.center,
                            style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                          ),
                        ],
                      ),
                    ),
                  ] else ...[
                    ListView.separated(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: matchingPolicies.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 12),
                      itemBuilder: (context, index) {
                        final p = matchingPolicies[index];
                        return GlassCard(
                          padding: const EdgeInsets.all(16),
                          borderRadius: 18,
                          onTap: () {
                            Navigator.pop(ctx);
                            context.push('/policy-detail/${p.id}');
                          },
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Expanded(
                                    child: Text(
                                      p.policyName,
                                      style: const TextStyle(
                                        fontSize: 14,
                                        fontWeight: FontWeight.w800,
                                        color: AppTheme.textPrimary,
                                      ),
                                    ),
                                  ),
                                  Container(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 8, vertical: 3),
                                    decoration: BoxDecoration(
                                      color: iconColor.withValues(alpha: 0.12),
                                      borderRadius: BorderRadius.circular(8),
                                    ),
                                    child: Text(
                                      p.policyCode,
                                      style: TextStyle(
                                        fontSize: 10,
                                        fontWeight: FontWeight.w700,
                                        color: iconColor,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                p.insurerName,
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: AppTheme.textSecondary,
                                ),
                              ),
                              const SizedBox(height: 10),
                              Row(
                                children: [
                                  const Icon(Icons.shield_rounded,
                                      size: 14, color: AppTheme.darkTeal),
                                  const SizedBox(width: 4),
                                  Text(
                                    'Limit: \$${p.coverageLimit.toStringAsFixed(0)}',
                                    style: const TextStyle(
                                      fontSize: 12,
                                      fontWeight: FontWeight.w700,
                                      color: AppTheme.darkTeal,
                                    ),
                                  ),
                                  const SizedBox(width: 14),
                                  const Icon(Icons.timer_outlined,
                                      size: 14, color: AppTheme.textMuted),
                                  const SizedBox(width: 4),
                                  Text(
                                    'Wait: ${p.waitingPeriodDays}d',
                                    style: const TextStyle(
                                      fontSize: 11,
                                      color: AppTheme.textSecondary,
                                    ),
                                  ),
                                ],
                              ),
                              if (p.description != null && p.description!.isNotEmpty) ...[
                                const SizedBox(height: 8),
                                Text(
                                  p.description!,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppTheme.textSecondary,
                                    height: 1.3,
                                  ),
                                ),
                              ],
                              const SizedBox(height: 12),
                              SizedBox(
                                width: double.infinity,
                                child: OutlinedButton.icon(
                                  onPressed: () {
                                    Navigator.pop(ctx);
                                    context.push('/policy-detail/${p.id}');
                                  },
                                  icon: const Icon(Icons.info_outline_rounded, size: 14),
                                  label: const Text('View Plan Details & Terms'),
                                  style: OutlinedButton.styleFrom(
                                    foregroundColor: AppTheme.darkTeal,
                                    side: const BorderSide(color: AppTheme.borderLight),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                  ],
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () {
                      Navigator.pop(ctx);
                      context.go('/policies');
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.darkTeal,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                    ),
                    child: const Text('Explore Full Policy Catalogue'),
                  ),
                  const SizedBox(height: 10),
                ],
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Section Header
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'Explore Coverage',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w800,
                color: AppTheme.textPrimary,
                letterSpacing: -0.3,
              ),
            ),
            GestureDetector(
              onTap: onViewAll,
              child: const Row(
                children: [
                  Text(
                    'View All',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.gradientSkyBlue,
                    ),
                  ),
                  SizedBox(width: 2),
                  Icon(
                    Icons.chevron_right_rounded,
                    size: 18,
                    color: AppTheme.gradientSkyBlue,
                  ),
                ],
              ),
            ),
          ],
        ),

        const SizedBox(height: 14),

        // Grid of 4 Policy Categories
        Row(
          children: [
            Expanded(
              child: _buildCategoryCard(
                context: context,
                categoryKey: 'MOTOR',
                title: 'Motor Insurance',
                subtitle: 'for Individuals',
                icon: Icons.directions_car_rounded,
                iconColor: const Color(0xFF8B5CF6),
                bgColor: const Color(0xFFF3E8FF),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _buildCategoryCard(
                context: context,
                categoryKey: 'HEALTH',
                title: 'Health Insurance',
                subtitle: 'for Families & SMEs',
                icon: Icons.health_and_safety_rounded,
                iconColor: const Color(0xFF0284C7),
                bgColor: const Color(0xFFE0F2FE),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: _buildCategoryCard(
                context: context,
                categoryKey: 'TRAVEL',
                title: 'Travel Insurance',
                subtitle: 'Worldwide trips',
                icon: Icons.flight_takeoff_rounded,
                iconColor: const Color(0xFF0D9488),
                bgColor: const Color(0xFFCCFBF1),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _buildCategoryCard(
                context: context,
                categoryKey: 'LIFE',
                title: 'Medical & Life',
                subtitle: 'Critical coverage',
                icon: Icons.medical_services_rounded,
                iconColor: const Color(0xFFEA580C),
                bgColor: const Color(0xFFFFEDD5),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildCategoryCard({
    required BuildContext context,
    required String categoryKey,
    required String title,
    required String subtitle,
    required IconData icon,
    required Color iconColor,
    required Color bgColor,
  }) {
    final count = _getPoliciesForCategory(categoryKey).length;

    return GlassCard(
      padding: const EdgeInsets.all(14),
      borderRadius: 20,
      onTap: () {
        _showCategoryPoliciesModal(
          context,
          categoryKey: categoryKey,
          title: title,
          icon: icon,
          iconColor: iconColor,
        );
      },
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: bgColor,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: iconColor, size: 20),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textPrimary,
                    letterSpacing: -0.2,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppTheme.textSecondary,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (count > 0) ...[
                  const SizedBox(height: 4),
                  Text(
                    '$count available',
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.gradientSkyBlue,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

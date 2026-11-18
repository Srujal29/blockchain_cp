import 'package:flutter/material.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/glass_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../models/evidence_analysis_model.dart';

class EvidenceAnalysisCard extends StatefulWidget {
  final EvidenceAnalysisReport report;
  final VoidCallback? onReanalyze;
  final bool isReanalyzing;

  const EvidenceAnalysisCard({
    super.key,
    required this.report,
    this.onReanalyze,
    this.isReanalyzing = false,
  });

  @override
  State<EvidenceAnalysisCard> createState() => _EvidenceAnalysisCardState();
}

class _EvidenceAnalysisCardState extends State<EvidenceAnalysisCard> {
  bool _expanded = false;

  Color _getStatusColor(String status) {
    switch (status.toUpperCase()) {
      case 'CONSISTENT':
        return AppTheme.success;
      case 'DISCREPANCIES_DETECTED':
        return AppTheme.warning;
      case 'NEEDS_MANUAL_REVIEW':
        return const Color(0xFFF97316); // Orange
      case 'FAILED':
        return AppTheme.error;
      default:
        return AppTheme.textSecondary;
    }
  }

  IconData _getStatusIcon(String status) {
    switch (status.toUpperCase()) {
      case 'CONSISTENT':
        return Icons.check_circle_rounded;
      case 'DISCREPANCIES_DETECTED':
        return Icons.warning_amber_rounded;
      case 'NEEDS_MANUAL_REVIEW':
        return Icons.rule_rounded;
      case 'FAILED':
        return Icons.error_outline_rounded;
      default:
        return Icons.help_outline_rounded;
    }
  }

  String _formatDocType(String type) {
    return type.replaceAll('_', ' ').toLowerCase().split(' ').map((w) {
      if (w.isEmpty) return '';
      return w[0].toUpperCase() + w.substring(1);
    }).join(' ');
  }

  @override
  Widget build(BuildContext context) {
    final report = widget.report;
    final statusColor = _getStatusColor(report.overallStatus);
    final statusIcon = _getStatusIcon(report.overallStatus);

    return GlassCard(
      margin: const EdgeInsets.only(top: 8, bottom: 12),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 1. Header: Document Type, Version & Status Badge
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Icon(
                    report.documentType.contains('MEDICAL')
                        ? Icons.local_hospital_rounded
                        : (report.documentType.contains('REPAIR')
                            ? Icons.car_repair_rounded
                            : Icons.receipt_long_rounded),
                    size: 20,
                    color: AppTheme.darkTeal,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _formatDocType(report.documentType),
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ],
              ),
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AppTheme.background,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: AppTheme.borderLight),
                    ),
                    child: Text(
                      'v${report.analysisVersion}${report.isLatest ? ' (Latest)' : ''}',
                      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
                    ),
                  ),
                  const SizedBox(width: 8),
                  StatusBadge(
                    label: report.overallStatus.replaceAll('_', ' '),
                    color: statusColor,
                    icon: statusIcon,
                  ),
                ],
              ),
            ],
          ),

          const SizedBox(height: 12),

          // 2. Advisory Recommendation Banner
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: statusColor.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: statusColor.withValues(alpha: 0.25)),
            ),
            child: Row(
              children: [
                Icon(statusIcon, size: 16, color: statusColor),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Recommendation: ${report.reviewRecommendation.replaceAll('_', ' ')}',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: statusColor,
                    ),
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: 12),

          // 3. Technical Metadata Badges
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              _buildMetaPill('Method: ${report.extractionMethod.replaceAll('_', ' ')}'),
              _buildMetaPill('Confidence: ${(report.confidenceScore * 100).toInt()}%'),
              _buildMetaPill('Engine: ${report.parserEngineVersion}'),
            ],
          ),

          const Divider(color: AppTheme.borderLight, height: 24),

          // 4. Extracted Key Entities
          const Text(
            'Extracted Document Data',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
          ),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.backgroundSurface,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppTheme.borderLight),
            ),
            child: Column(
              children: [
                _buildDataRow('Provider / Facility', report.extractedProviderName ?? 'Not detected'),
                if (report.extractedTaxId != null)
                  _buildDataRow('Tax ID / GSTIN', report.extractedTaxId!),
                if (report.extractedInvoiceNumber != null)
                  _buildDataRow('Invoice / Ref #', report.extractedInvoiceNumber!),
                if (report.extractedInvoiceDate != null)
                  _buildDataRow('Invoice Date', report.extractedInvoiceDate!),
                if (report.extractedAdmissionDate != null)
                  _buildDataRow('Admission Date', report.extractedAdmissionDate!),
                if (report.extractedDischargeDate != null)
                  _buildDataRow('Discharge Date', report.extractedDischargeDate!),
                if (report.extractedInspectionDate != null)
                  _buildDataRow('Inspection Date', report.extractedInspectionDate!),
                if (report.extractedRepairDate != null)
                  _buildDataRow('Repair Date', report.extractedRepairDate!),
              ],
            ),
          ),

          const SizedBox(height: 14),

          // 5. Deterministic Arithmetic & Discrepancy Checks
          const Text(
            'Arithmetic & Timeline Integrity Audit',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
          ),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.cardWhite,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppTheme.borderLight),
            ),
            child: Column(
              children: [
                _buildAuditItem(
                  'Extracted Total Amount',
                  report.extractedTotalAmount != null
                      ? '₹${report.extractedTotalAmount!.toStringAsFixed(2)}'
                      : 'Not extracted',
                  null,
                ),
                _buildAuditItem(
                  'Calculated Line Items Sum',
                  report.calculatedLineItemsSum != null
                      ? '₹${report.calculatedLineItemsSum!.toStringAsFixed(2)}'
                      : 'Inconclusive',
                  null,
                ),
                _buildAuditItem(
                  'Sum vs Extracted Total',
                  report.sumMatchesTotal == true
                      ? 'Matches Exact'
                      : (report.sumMatchesTotal == false
                          ? 'Mismatch (Diff: ₹${report.roundingOrTaxDiscrepancy?.toStringAsFixed(2) ?? '0.00'})'
                          : 'Inconclusive'),
                  report.sumMatchesTotal,
                ),
                _buildAuditItem(
                  'Invoice Total vs Claimed Amount',
                  report.amountMatchesClaim == true
                      ? 'Matches Claim Amount'
                      : (report.amountMatchesClaim == false
                          ? 'Mismatch (Diff: ₹${report.invoiceVsClaimAmountDiscrepancy?.toStringAsFixed(2) ?? '0.00'})'
                          : 'Inconclusive'),
                  report.amountMatchesClaim,
                ),
                _buildAuditItem(
                  'Line Item Math (Qty × Rate)',
                  report.lineItemMathValid == true
                      ? 'All Items Valid'
                      : (report.lineItemMathValid == false ? 'Calculation Inconsistent' : 'Inconclusive'),
                  report.lineItemMathValid,
                ),
                _buildAuditItem(
                  'Chronological Timeline',
                  report.timelineValid == true
                      ? 'Consistent Sequence'
                      : (report.timelineValid == false ? 'Inverted Chronology' : 'Inconclusive'),
                  report.timelineValid,
                ),
              ],
            ),
          ),

          // 6. Discrepancy Findings Callouts (if any)
          if (report.discrepancyFlags.isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppTheme.warning.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppTheme.warning.withValues(alpha: 0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.warning_amber_rounded, size: 16, color: AppTheme.warning),
                      SizedBox(width: 6),
                      Text(
                        'Audit Discrepancy Findings',
                        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: AppTheme.warning),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  ...report.discrepancyFlags.map(
                    (flag) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2.0),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('• ', style: TextStyle(color: AppTheme.warning, fontWeight: FontWeight.bold)),
                          Expanded(
                            child: Text(
                              flag,
                              style: const TextStyle(fontSize: 11, color: AppTheme.textPrimary),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],

          // 7. Expandable Line Items breakdown
          if (report.extractedLineItems.isNotEmpty) ...[
            const SizedBox(height: 8),
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                initiallyExpanded: _expanded,
                onExpansionChanged: (v) => setState(() => _expanded = v),
                title: Text(
                  'Extracted Line Items (${report.extractedLineItems.length})',
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textSecondary),
                ),
                children: report.extractedLineItems.map((item) {
                  return Container(
                    margin: const EdgeInsets.only(bottom: 6),
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    decoration: BoxDecoration(
                      color: AppTheme.backgroundSurface,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: AppTheme.borderLight),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                item['description']?.toString() ?? '',
                                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AppTheme.textPrimary),
                              ),
                              if (item['quantity'] != null && item['unit_rate'] != null)
                                Text(
                                  'Qty: ${item['quantity']} × ₹${item['unit_rate']}',
                                  style: const TextStyle(fontSize: 10, color: AppTheme.textSecondary),
                                ),
                            ],
                          ),
                        ),
                        Text(
                          '₹${(item['total'] as num?)?.toStringAsFixed(2) ?? '0.00'}',
                          style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: AppTheme.textPrimary),
                        ),
                      ],
                    ),
                  );
                }).toList(),
              ),
            ),
          ],

          // 8. Re-Analyze Action Button (Authority or Customer re-trigger)
          if (widget.onReanalyze != null) ...[
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: widget.isReanalyzing ? null : widget.onReanalyze,
                icon: widget.isReanalyzing
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.refresh_rounded, size: 14),
                label: Text(
                  widget.isReanalyzing ? 'Analyzing...' : 'Re-Analyze Evidence',
                  style: const TextStyle(fontSize: 11),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildMetaPill(String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: AppTheme.backgroundSurface,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppTheme.borderLight),
      ),
      child: Text(
        label,
        style: const TextStyle(fontSize: 10, color: AppTheme.textSecondary, fontWeight: FontWeight.w600),
      ),
    );
  }

  Widget _buildDataRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3.0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary)),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAuditItem(String label, String value, bool? outcome) {
    Color valColor = AppTheme.textPrimary;
    if (outcome == true) valColor = AppTheme.success;
    if (outcome == false) valColor = AppTheme.warning;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4.0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Text(label, style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary)),
          ),
          Row(
            children: [
              if (outcome == true)
                const Icon(Icons.check_circle_rounded, size: 13, color: AppTheme.success),
              if (outcome == false)
                const Icon(Icons.warning_rounded, size: 13, color: AppTheme.warning),
              if (outcome != null) const SizedBox(width: 4),
              Text(
                value,
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: valColor),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

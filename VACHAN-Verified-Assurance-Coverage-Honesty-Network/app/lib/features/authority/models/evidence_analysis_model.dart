/// Model representing an Evidence Analysis Report for Phase 6.
class EvidenceAnalysisReport {
  final String id;
  final String evidenceId;
  final String claimId;
  final int analysisVersion;
  final bool isLatest;
  final String documentType;
  final String extractionMethod;
  final String parserEngineVersion;
  final double confidenceScore;

  // Extracted fields
  final String? extractedProviderName;
  final String? extractedTaxId;
  final String? extractedInvoiceNumber;
  final String? extractedInvoiceDate;
  final String? extractedAdmissionDate;
  final String? extractedDischargeDate;
  final String? extractedInspectionDate;
  final String? extractedRepairDate;

  // Monetary figures
  final double? extractedSubtotal;
  final double? extractedTaxAmount;
  final double? extractedDiscountAmount;
  final double? extractedTotalAmount;
  final List<Map<String, dynamic>> extractedLineItems;

  // Arithmetic & Timeline checks
  final bool? lineItemMathValid;
  final bool? sumMatchesTotal;
  final double? calculatedLineItemsSum;
  final double? roundingOrTaxDiscrepancy;
  final bool? amountMatchesClaim;
  final double? invoiceVsClaimAmountDiscrepancy;
  final bool? timelineValid;
  final List<String> timelineFindings;
  final List<String> discrepancyFlags;

  final String overallStatus;
  final String reviewRecommendation;
  final String? rawExtractedText;
  final String createdAt;

  const EvidenceAnalysisReport({
    required this.id,
    required this.evidenceId,
    required this.claimId,
    required this.analysisVersion,
    required this.isLatest,
    required this.documentType,
    required this.extractionMethod,
    required this.parserEngineVersion,
    required this.confidenceScore,
    this.extractedProviderName,
    this.extractedTaxId,
    this.extractedInvoiceNumber,
    this.extractedInvoiceDate,
    this.extractedAdmissionDate,
    this.extractedDischargeDate,
    this.extractedInspectionDate,
    this.extractedRepairDate,
    this.extractedSubtotal,
    this.extractedTaxAmount,
    this.extractedDiscountAmount,
    this.extractedTotalAmount,
    this.extractedLineItems = const [],
    this.lineItemMathValid,
    this.sumMatchesTotal,
    this.calculatedLineItemsSum,
    this.roundingOrTaxDiscrepancy,
    this.amountMatchesClaim,
    this.invoiceVsClaimAmountDiscrepancy,
    this.timelineValid,
    this.timelineFindings = const [],
    this.discrepancyFlags = const [],
    required this.overallStatus,
    required this.reviewRecommendation,
    this.rawExtractedText,
    required this.createdAt,
  });

  factory EvidenceAnalysisReport.fromJson(Map<String, dynamic> json) {
    double? parseDouble(dynamic v) {
      if (v == null) return null;
      if (v is num) return v.toDouble();
      return double.tryParse(v.toString());
    }

    List<Map<String, dynamic>> parseLineItems(dynamic raw) {
      if (raw is List) {
        return raw.map((item) => Map<String, dynamic>.from(item as Map)).toList();
      }
      return const [];
    }

    List<String> parseStringList(dynamic raw) {
      if (raw is List) {
        return raw.map((item) => item.toString()).toList();
      }
      return const [];
    }

    return EvidenceAnalysisReport(
      id: json['id']?.toString() ?? '',
      evidenceId: json['evidence_id']?.toString() ?? '',
      claimId: json['claim_id']?.toString() ?? '',
      analysisVersion: json['analysis_version'] is int ? json['analysis_version'] : int.tryParse(json['analysis_version']?.toString() ?? '1') ?? 1,
      isLatest: json['is_latest'] == true,
      documentType: json['document_type']?.toString() ?? 'UNKNOWN',
      extractionMethod: json['extraction_method']?.toString() ?? 'MANUAL_FALLBACK',
      parserEngineVersion: json['parser_engine_version']?.toString() ?? 'vachan-extractor-1.0',
      confidenceScore: parseDouble(json['confidence_score']) ?? 1.0,
      extractedProviderName: json['extracted_provider_name']?.toString(),
      extractedTaxId: json['extracted_tax_id']?.toString(),
      extractedInvoiceNumber: json['extracted_invoice_number']?.toString(),
      extractedInvoiceDate: json['extracted_invoice_date']?.toString(),
      extractedAdmissionDate: json['extracted_admission_date']?.toString(),
      extractedDischargeDate: json['extracted_discharge_date']?.toString(),
      extractedInspectionDate: json['extracted_inspection_date']?.toString(),
      extractedRepairDate: json['extracted_repair_date']?.toString(),
      extractedSubtotal: parseDouble(json['extracted_subtotal']),
      extractedTaxAmount: parseDouble(json['extracted_tax_amount']),
      extractedDiscountAmount: parseDouble(json['extracted_discount_amount']),
      extractedTotalAmount: parseDouble(json['extracted_total_amount']),
      extractedLineItems: parseLineItems(json['extracted_line_items']),
      lineItemMathValid: json['line_item_math_valid'] as bool?,
      sumMatchesTotal: json['sum_matches_total'] as bool?,
      calculatedLineItemsSum: parseDouble(json['calculated_line_items_sum']),
      roundingOrTaxDiscrepancy: parseDouble(json['rounding_or_tax_discrepancy']),
      amountMatchesClaim: json['amount_matches_claim'] as bool?,
      invoiceVsClaimAmountDiscrepancy: parseDouble(json['invoice_vs_claim_amount_discrepancy']),
      timelineValid: json['timeline_valid'] as bool?,
      timelineFindings: parseStringList(json['timeline_findings']),
      discrepancyFlags: parseStringList(json['discrepancy_flags']),
      overallStatus: json['overall_status']?.toString() ?? 'PENDING',
      reviewRecommendation: json['review_recommendation']?.toString() ?? 'NO_ACTION_REQUIRED',
      rawExtractedText: json['raw_extracted_text']?.toString(),
      createdAt: json['created_at']?.toString() ?? '',
    );
  }
}


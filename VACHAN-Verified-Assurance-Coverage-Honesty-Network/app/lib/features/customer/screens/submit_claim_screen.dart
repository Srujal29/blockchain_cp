import 'dart:io';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_text_field.dart';
import '../../../shared/widgets/glass_card.dart';
import '../models/customer_policy_model.dart';
import '../models/evidence_upload_item.dart';
import '../providers/customer_provider.dart';

class SubmitClaimScreen extends ConsumerStatefulWidget {
  const SubmitClaimScreen({super.key});

  @override
  ConsumerState<SubmitClaimScreen> createState() => _SubmitClaimScreenState();
}

class _SubmitClaimScreenState extends ConsumerState<SubmitClaimScreen> {
  final _formKey = GlobalKey<FormState>();
  final _amountController = TextEditingController();
  final _descriptionController = TextEditingController();

  CustomerRegistrationModel? _selectedRegistration;
  String _selectedCategory = 'MEDICAL'; // VEHICLE, MEDICAL, GENERIC
  DateTime _incidentDate = DateTime.now();
  bool _isSubmitting = false;

  // Real File Evidence State
  final List<EvidenceUploadItem> _selectedEvidence = [];
  String? _createdClaimId;
  String? _createdClaimNumber;
  String _defaultEvidenceType = 'MEDICAL_REPORT';

  @override
  void initState() {
    super.initState();
    final dashboard = ref.read(customerDashboardProvider);
    if (dashboard.activePolicies.isNotEmpty) {
      _selectedRegistration = dashboard.activePolicies.first;
    }
  }

  @override
  void dispose() {
    _amountController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _incidentDate,
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (picked != null) {
      setState(() => _incidentDate = picked);
    }
  }

  void _onCategoryChanged(String key) {
    setState(() {
      _selectedCategory = key;
      if (key == 'VEHICLE') {
        _defaultEvidenceType = 'INCIDENT_PHOTO';
      } else if (key == 'MEDICAL') {
        _defaultEvidenceType = 'MEDICAL_REPORT';
      } else {
        _defaultEvidenceType = 'SUPPORTING_DOCUMENT';
      }
    });
  }

  Future<void> _pickEvidenceFiles() async {
    if (_selectedEvidence.length >= EvidenceUploadItem.maxFilesPerClaim) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Maximum 5 evidence files allowed per claim.'),
          backgroundColor: AppTheme.warning,
        ),
      );
      return;
    }

    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: EvidenceUploadItem.allowedExtensions.toList(),
      allowMultiple: true,
      withReadStream: true,
      withData: false,
    );

    if (result == null || result.files.isEmpty) return;

    final existingKeys = _selectedEvidence.map((e) => e.duplicateKey).toSet();
    final errors = <String>[];

    setState(() {
      for (final file in result.files) {
        if (_selectedEvidence.length >= EvidenceUploadItem.maxFilesPerClaim) {
          errors.add('Maximum 5 files per claim reached; extra files skipped.');
          break;
        }
        final validationError = EvidenceUploadItem.validateFile(file.name, file.size);
        if (validationError != null) {
          errors.add(validationError);
          continue;
        }
        final mime = EvidenceUploadItem.inferMimeType(file.name);
        if (mime == null) {
          errors.add('Unsupported file "${file.name}".');
          continue;
        }
        final item = EvidenceUploadItem(
          id: '${DateTime.now().microsecondsSinceEpoch}_${file.name}',
          filename: file.name,
          sizeBytes: file.size,
          mimeType: mime,
          evidenceType: _defaultEvidenceType,
          filePath: file.path,
          streamFactory: file.readStream != null ? () => file.readStream! : null,
          bytes: file.bytes,
        );
        if (existingKeys.contains(item.duplicateKey)) {
          errors.add('Duplicate file "${file.name}" skipped.');
          continue;
        }
        existingKeys.add(item.duplicateKey);
        _selectedEvidence.add(item);
      }
    });

    if (errors.isNotEmpty && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(errors.first),
          backgroundColor: AppTheme.warning,
        ),
      );
    }
  }

  Future<void> _handleSubmit() async {
    if (_createdClaimId == null) {
      if (!_formKey.currentState!.validate()) return;
      if (_selectedRegistration == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Please select an active policy registration.'),
            backgroundColor: AppTheme.error,
          ),
        );
        return;
      }
    }

    final amount = double.tryParse(_amountController.text.trim());
    if (_createdClaimId == null && (amount == null || amount <= 0)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please enter a valid positive claim amount.'),
          backgroundColor: AppTheme.error,
        ),
      );
      return;
    }

    setState(() => _isSubmitting = true);

    final notifier = ref.read(claimsListProvider.notifier);

    // 1. Create the claim only once
    if (_createdClaimId == null) {
      final incidentDateStr =
          "${_incidentDate.year}-${_incidentDate.month.toString().padLeft(2, '0')}-${_incidentDate.day.toString().padLeft(2, '0')}";
      final newClaim = await notifier.createClaimOnly(
        registrationId: _selectedRegistration!.id,
        claimCategory: _selectedCategory,
        requestedAmount: amount!,
        incidentDate: incidentDateStr,
        description: _descriptionController.text.trim(),
      );

      if (newClaim == null) {
        if (mounted) {
          setState(() => _isSubmitting = false);
          final err = ref.read(claimsListProvider).errorMessage ?? 'Claim submission failed.';
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(err), backgroundColor: AppTheme.error),
          );
        }
        return;
      }
      _createdClaimId = newClaim.id;
      _createdClaimNumber = newClaim.claimNumber;
    }

    // 2. Upload pending or previously failed files (never re-upload succeeded ones)
    bool anyFailed = false;
    for (final item in _selectedEvidence) {
      if (item.status == EvidenceUploadStatus.uploaded) continue;
      setState(() {
        item.status = EvidenceUploadStatus.uploading;
        item.progress = 0.0;
        item.errorMessage = null;
      });
      try {
        await notifier.uploadEvidenceItem(
          claimId: _createdClaimId!,
          item: item,
          onProgress: (p) {
            if (mounted) {
              setState(() => item.progress = p);
            }
          },
        );
        if (mounted) {
          setState(() {
            item.status = EvidenceUploadStatus.uploaded;
            item.progress = 1.0;
          });
        }
      } catch (e) {
        anyFailed = true;
        if (mounted) {
          setState(() {
            item.status = EvidenceUploadStatus.failed;
            item.errorMessage = e.toString();
          });
        }
      }
    }

    if (anyFailed) {
      if (mounted) {
        setState(() => _isSubmitting = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Claim $_createdClaimNumber was saved, but some evidence uploads failed. Please retry failed files.',
            ),
            backgroundColor: AppTheme.error,
          ),
        );
      }
      return;
    }

    // 3. Run deterministic assessment only after all uploads succeed
    try {
      await notifier.assessClaim(_createdClaimId!);
    } catch (_) {}

    if (!mounted) return;
    setState(() => _isSubmitting = false);
    ref.read(customerDashboardProvider.notifier).fetchDashboardData();

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          _selectedEvidence.isNotEmpty
              ? 'Claim $_createdClaimNumber filed with ${_selectedEvidence.length} evidence file(s)!'
              : 'Claim $_createdClaimNumber submitted successfully!',
        ),
        backgroundColor: AppTheme.success,
      ),
    );
    context.pushReplacement('/claim-detail/$_createdClaimId');
  }

  @override
  Widget build(BuildContext context) {
    final dashboard = ref.watch(customerDashboardProvider);
    final activeRegs = dashboard.activePolicies;

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('File an Insurance Claim'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          onPressed: () => context.pop(),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 12.0),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Incident & Policy Details',
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                    letterSpacing: -0.4,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  'Claims must be filed against active confirmed policy registrations.',
                  style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 20),

                // Registration Selector
                if (activeRegs.isEmpty) ...[
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AppTheme.warning.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: AppTheme.warning.withValues(alpha: 0.3)),
                    ),
                    child: const Row(
                      children: [
                        Icon(Icons.warning_amber_rounded, color: AppTheme.warning, size: 24),
                        SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            'You do not have any active confirmed policies. You must have an active policy to file claims.',
                            style: TextStyle(
                                fontSize: 12,
                                color: Color(0xFF92400E),
                                fontWeight: FontWeight.w500),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                ] else ...[
                  const Text(
                    'Select Insured Policy',
                    style: TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: AppTheme.borderLight),
                    ),
                    child: DropdownButtonHideUnderline(
                      child: DropdownButton<CustomerRegistrationModel>(
                        isExpanded: true,
                        value: _selectedRegistration ?? activeRegs.first,
                        items: activeRegs.map((reg) {
                          return DropdownMenuItem(
                            value: reg,
                            child: Text(
                              'Policy #${reg.policyId.substring(0, reg.policyId.length > 8 ? 8 : reg.policyId.length)} (${reg.id.substring(0, 8)})',
                              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                            ),
                          );
                        }).toList(),
                        onChanged: (val) {
                          if (val != null) setState(() => _selectedRegistration = val);
                        },
                      ),
                    ),
                  ),
                  const SizedBox(height: 18),
                ],

                // Category Selector
                const Text(
                  'Claim Category',
                  style: TextStyle(
                      fontSize: 14, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    _buildCategoryRadio('MEDICAL', 'Medical / Health', Icons.medical_services_rounded),
                    const SizedBox(width: 8),
                    _buildCategoryRadio('VEHICLE', 'Motor / Vehicle', Icons.directions_car_rounded),
                    const SizedBox(width: 8),
                    _buildCategoryRadio('GENERIC', 'General', Icons.folder_outlined),
                  ],
                ),

                const SizedBox(height: 18),

                // Requested Amount & Incident Date
                GlassCard(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    children: [
                      AppTextField(
                        controller: _amountController,
                        labelText: 'Requested Amount (\$)',
                        hintText: 'e.g. 25000.00',
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        prefixIcon: const Icon(Icons.attach_money_rounded,
                            color: AppTheme.textMuted, size: 20),
                        validator: (value) {
                          if (value == null || value.trim().isEmpty) {
                            return 'Please enter requested amount';
                          }
                          final val = double.tryParse(value.trim());
                          if (val == null || val <= 0) return 'Must be greater than 0';
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),
                      // Incident Date Picker
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                'Date of Incident',
                                style: TextStyle(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600,
                                    color: AppTheme.textPrimary),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                "${_incidentDate.year}-${_incidentDate.month.toString().padLeft(2, '0')}-${_incidentDate.day.toString().padLeft(2, '0')}",
                                style: const TextStyle(
                                    fontSize: 15,
                                    fontWeight: FontWeight.w700,
                                    color: AppTheme.darkTeal),
                              ),
                            ],
                          ),
                          OutlinedButton.icon(
                            icon: const Icon(Icons.calendar_today_rounded, size: 16),
                            label: const Text('Change Date'),
                            onPressed: _pickDate,
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      AppTextField(
                        controller: _descriptionController,
                        labelText: 'Detailed Incident Description',
                        hintText:
                            'Describe the incident, damage, or treatment in detail (min 10 characters)...',
                        maxLines: 4,
                        validator: (value) {
                          if (value == null || value.trim().length < 10) {
                            return 'Please provide at least 10 characters describing the incident';
                          }
                          return null;
                        },
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 20),

                // ==============================================================
                // Supporting Evidence Proof Attachment Section
                // ==============================================================
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Expanded(
                      child: Text(
                        'Supporting Evidence Proof',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton.icon(
                      onPressed: _isSubmitting ? null : _pickEvidenceFiles,
                      icon: const Icon(Icons.upload_file_rounded, size: 18),
                      label: Text('Add Files (${_selectedEvidence.length}/5)'),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                const Text(
                  'Select PDF, JPG, JPEG, or PNG files (max 10 MB each, up to 5 files). Stored privately in Cloudinary.',
                  style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                ),
                const SizedBox(height: 10),

                if (_createdClaimId != null &&
                    _selectedEvidence.any((e) => e.status == EvidenceUploadStatus.failed)) ...[
                  Container(
                    width: double.infinity,
                    margin: const EdgeInsets.only(bottom: 12),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: AppTheme.error.withValues(alpha: 0.08),
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: AppTheme.error.withValues(alpha: 0.3)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Incomplete Upload for Claim $_createdClaimNumber',
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w800,
                            color: AppTheme.error,
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          'Your claim was saved once, but one or more evidence files failed to upload. Retry failed files below or view the claim.',
                          style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                        ),
                        const SizedBox(height: 8),
                        TextButton(
                          onPressed: _isSubmitting
                              ? null
                              : () => context.pushReplacement('/claim-detail/$_createdClaimId'),
                          child: const Text('Open Claim Without Failed Files'),
                        ),
                      ],
                    ),
                  ),
                ],

                if (_selectedEvidence.isEmpty) ...[
                  const GlassCard(
                    padding: EdgeInsets.all(16),
                    child: Row(
                      children: [
                        Icon(Icons.folder_open_rounded, color: AppTheme.textMuted, size: 22),
                        SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'No evidence files selected yet. Tap "Add Files" to attach medical bills, reports, or photos.',
                            style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                          ),
                        ),
                      ],
                    ),
                  ),
                ] else ...[
                  ..._selectedEvidence.asMap().entries.map((entry) {
                    final idx = entry.key;
                    final item = entry.value;
                    final sizeLabel = item.sizeBytes >= 1024 * 1024
                        ? '${(item.sizeBytes / (1024 * 1024)).toStringAsFixed(2)} MB'
                        : '${(item.sizeBytes / 1024).toStringAsFixed(1)} KB';

                    return GlassCard(
                      margin: const EdgeInsets.only(bottom: 10),
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              if (item.isImage && item.filePath != null)
                                ClipRRect(
                                  borderRadius: BorderRadius.circular(8),
                                  child: Image.file(
                                    File(item.filePath!),
                                    width: 40,
                                    height: 40,
                                    fit: BoxFit.cover,
                                    errorBuilder: (_, __, ___) => const Icon(
                                      Icons.image_rounded,
                                      color: AppTheme.gradientSkyBlue,
                                      size: 28,
                                    ),
                                  ),
                                )
                              else
                                Icon(
                                  item.isImage ? Icons.image_rounded : Icons.picture_as_pdf_rounded,
                                  color: item.isImage ? AppTheme.gradientSkyBlue : AppTheme.error,
                                  size: 28,
                                ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      item.filename,
                                      style: const TextStyle(
                                        fontSize: 13,
                                        fontWeight: FontWeight.w700,
                                        color: AppTheme.textPrimary,
                                      ),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                    Text(
                                      '$sizeLabel • ${item.status.name.toUpperCase()}',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w600,
                                        color: item.status == EvidenceUploadStatus.uploaded
                                            ? AppTheme.success
                                            : item.status == EvidenceUploadStatus.failed
                                                ? AppTheme.error
                                                : AppTheme.textSecondary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              if (!_isSubmitting && item.status != EvidenceUploadStatus.uploaded)
                                IconButton(
                                  icon: const Icon(Icons.close_rounded, size: 18, color: AppTheme.textMuted),
                                  onPressed: () => setState(() => _selectedEvidence.removeAt(idx)),
                                ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          DropdownButtonFormField<String>(
                            initialValue: item.evidenceType,
                            isExpanded: true,
                            decoration: const InputDecoration(
                              isDense: true,
                              contentPadding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                              border: OutlineInputBorder(),
                            ),
                            items: EvidenceUploadItem.allowedEvidenceTypes
                                .map((t) => DropdownMenuItem(value: t, child: Text(t, style: const TextStyle(fontSize: 12))))
                                .toList(),
                            onChanged: (_isSubmitting || item.status == EvidenceUploadStatus.uploaded)
                                ? null
                                : (val) {
                                    if (val != null) setState(() => item.evidenceType = val);
                                  },
                          ),
                          if (item.status == EvidenceUploadStatus.uploading) ...[
                            const SizedBox(height: 8),
                            LinearProgressIndicator(value: item.progress > 0 ? item.progress : null),
                          ],
                          if (item.status == EvidenceUploadStatus.failed && item.errorMessage != null) ...[
                            const SizedBox(height: 6),
                            Text(
                              item.errorMessage!,
                              style: const TextStyle(fontSize: 11, color: AppTheme.error),
                            ),
                          ],
                        ],
                      ),
                    );
                  }),
                ],

                const SizedBox(height: 24),

                AppButton(
                  label: _createdClaimId != null
                      ? 'Retry Failed Uploads'
                      : _selectedEvidence.isNotEmpty
                          ? 'Submit Claim with ${_selectedEvidence.length} File(s)'
                          : 'Submit Claim for Evaluation',
                  isLoading: _isSubmitting,
                  onPressed: activeRegs.isEmpty ? null : _handleSubmit,
                  variant: AppButtonVariant.primaryGradient,
                ),

                const SizedBox(height: 24),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCategoryRadio(String key, String label, IconData icon) {
    final isSelected = _selectedCategory == key;
    return Expanded(
      child: GestureDetector(
        onTap: () => _onCategoryChanged(key),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 6),
          decoration: BoxDecoration(
            color: isSelected ? AppTheme.darkTeal : Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: isSelected ? AppTheme.darkTeal : AppTheme.borderLight,
            ),
          ),
          child: Column(
            children: [
              Icon(icon,
                  size: 20,
                  color: isSelected ? Colors.white : AppTheme.textSecondary),
              const SizedBox(height: 4),
              Text(
                label,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: isSelected ? Colors.white : AppTheme.textSecondary,
                ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

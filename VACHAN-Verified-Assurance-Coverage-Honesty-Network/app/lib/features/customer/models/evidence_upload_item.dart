import 'dart:typed_data';

enum EvidenceUploadStatus {
  pending,
  uploading,
  uploaded,
  failed,
}

class EvidenceUploadItem {
  static const int maxFileSizeBytes = 10 * 1024 * 1024; // 10 MB
  static const int maxFilesPerClaim = 5;
  static const Set<String> allowedExtensions = {'pdf', 'jpg', 'jpeg', 'png'};

  static const List<String> allowedEvidenceTypes = [
    'MEDICAL_REPORT',
    'MEDICAL_BILL',
    'DISCHARGE_SUMMARY',
    'PRESCRIPTION',
    'REGISTRATION_CERTIFICATE',
    'DRIVING_LICENSE',
    'INCIDENT_PHOTO',
    'REPAIR_ESTIMATE',
    'SUPPORTING_DOCUMENT',
  ];

  final String id;
  final String filename;
  final int sizeBytes;
  final String mimeType;
  String evidenceType;
  final String? filePath;
  final Stream<List<int>> Function()? streamFactory;
  final Uint8List? bytes;
  double progress;
  EvidenceUploadStatus status;
  String? errorMessage;

  EvidenceUploadItem({
    required this.id,
    required this.filename,
    required this.sizeBytes,
    required this.mimeType,
    required this.evidenceType,
    this.filePath,
    this.streamFactory,
    this.bytes,
    this.progress = 0.0,
    this.status = EvidenceUploadStatus.pending,
    this.errorMessage,
  });

  String get duplicateKey => '${filename.trim().toLowerCase()}_$sizeBytes';

  bool get isImage =>
      mimeType == 'image/jpeg' || mimeType == 'image/png';

  static String? inferMimeType(String filename) {
    final ext = filename.split('.').last.toLowerCase();
    switch (ext) {
      case 'pdf':
        return 'application/pdf';
      case 'jpg':
      case 'jpeg':
        return 'image/jpeg';
      case 'png':
        return 'image/png';
      default:
        return null;
    }
  }

  static String? validateFile(String filename, int sizeBytes) {
    final parts = filename.split('.');
    final ext = parts.length > 1 ? parts.last.toLowerCase() : '';
    if (!allowedExtensions.contains(ext)) {
      return 'Unsupported file "$filename". Only PDF, JPG, JPEG, and PNG are allowed.';
    }
    if (sizeBytes <= 0) {
      return 'File "$filename" is empty.';
    }
    if (sizeBytes > maxFileSizeBytes) {
      return 'File "$filename" exceeds the 10 MB limit.';
    }
    return null;
  }
}


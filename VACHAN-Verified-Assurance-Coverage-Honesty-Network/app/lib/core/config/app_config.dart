import 'package:flutter/foundation.dart';

/// Central application configuration.
/// The backend API base URL can be supplied at compile time via:
/// `--dart-define=API_BASE_URL=https://api.yourdomain.com/api/v1`
class AppConfig {
  static const String _envBaseUrl = String.fromEnvironment('API_BASE_URL');

  static const String androidEmulatorBaseUrl = 'http://10.0.2.2:8000/api/v1';
  static const String localLoopbackBaseUrl = 'http://127.0.0.1:8000/api/v1';

  static String get defaultBaseUrl {
    if (_envBaseUrl.isNotEmpty) {
      return _envBaseUrl;
    }
    if (kDebugMode) {
      if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
        return androidEmulatorBaseUrl;
      }
      return localLoopbackBaseUrl;
    }
    // Release builds must supply an explicit HTTPS API_BASE_URL via --dart-define or ServerConfigDialog
    return '';
  }

  static String apiBaseUrl = defaultBaseUrl;

  static const Duration connectTimeout = Duration(seconds: 30);
  static const Duration receiveTimeout = Duration(seconds: 120);

  static const String appName = 'InsureChain VoiceGuard';
  static const String appTagline = 'Verifiable Trust & AI Voice Assurance';
}

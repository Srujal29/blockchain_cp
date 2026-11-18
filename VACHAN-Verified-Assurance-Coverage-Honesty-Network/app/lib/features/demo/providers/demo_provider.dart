import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../auth/providers/auth_provider.dart';
import '../models/demo_scenario_model.dart';
import '../services/demo_api_service.dart';

final demoApiServiceProvider = Provider<DemoApiService>((ref) {
  final apiClient = ref.watch(apiClientProvider);
  return DemoApiService(apiClient: apiClient);
});

final demoScenariosProvider = FutureProvider<List<DemoScenarioModel>>((ref) async {
  final apiService = ref.watch(demoApiServiceProvider);
  return await apiService.getScenarios();
});

class DemoState {
  final bool isLoading;
  final String? activeScenarioId;
  final DemoSeedResultModel? lastSeedResult;
  final DemoTamperCheckResultModel? tamperCheckResult;
  final DemoCleanupResultModel? cleanupResult;
  final String? errorMessage;

  const DemoState({
    this.isLoading = false,
    this.activeScenarioId,
    this.lastSeedResult,
    this.tamperCheckResult,
    this.cleanupResult,
    this.errorMessage,
  });

  DemoState copyWith({
    bool? isLoading,
    String? activeScenarioId,
    DemoSeedResultModel? lastSeedResult,
    DemoTamperCheckResultModel? tamperCheckResult,
    DemoCleanupResultModel? cleanupResult,
    String? errorMessage,
  }) {
    return DemoState(
      isLoading: isLoading ?? this.isLoading,
      activeScenarioId: activeScenarioId ?? this.activeScenarioId,
      lastSeedResult: lastSeedResult ?? this.lastSeedResult,
      tamperCheckResult: tamperCheckResult ?? this.tamperCheckResult,
      cleanupResult: cleanupResult ?? this.cleanupResult,
      errorMessage: errorMessage,
    );
  }
}

class DemoNotifier extends StateNotifier<DemoState> {
  final DemoApiService apiService;

  DemoNotifier({required this.apiService}) : super(const DemoState());

  Future<DemoSeedResultModel?> seedScenario(String scenarioId) async {
    state = state.copyWith(isLoading: true, activeScenarioId: scenarioId, errorMessage: null);
    try {
      final res = await apiService.seedScenario(scenarioId);
      state = state.copyWith(isLoading: false, lastSeedResult: res);
      return res;
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
      return null;
    }
  }

  Future<List<DemoSeedResultModel>?> seedAll() async {
    state = state.copyWith(isLoading: true, activeScenarioId: 'ALL', errorMessage: null);
    try {
      final res = await apiService.seedAllScenarios();
      state = state.copyWith(isLoading: false);
      return res;
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
      return null;
    }
  }

  Future<DemoTamperCheckResultModel?> runTamperCheck() async {
    state = state.copyWith(isLoading: true, activeScenarioId: 'DEMO-SCN-15', errorMessage: null);
    try {
      final res = await apiService.runTamperCheck();
      state = state.copyWith(isLoading: false, tamperCheckResult: res);
      return res;
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
      return null;
    }
  }

  Future<DemoCleanupResultModel?> cleanup() async {
    state = state.copyWith(isLoading: true, errorMessage: null);
    try {
      final res = await apiService.cleanupDemoData();
      state = state.copyWith(isLoading: false, cleanupResult: res);
      return res;
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
      return null;
    }
  }
}

final demoNotifierProvider = StateNotifierProvider<DemoNotifier, DemoState>((ref) {
  final apiService = ref.watch(demoApiServiceProvider);
  return DemoNotifier(apiService: apiService);
});


import '../../../core/network/api_client.dart';
import '../models/demo_scenario_model.dart';

class DemoApiService {
  final ApiClient apiClient;

  DemoApiService({required this.apiClient});

  Future<List<DemoScenarioModel>> getScenarios() async {
    try {
      final response = await apiClient.dio.get('/demo/scenarios');
      final list = (response.data as List)
          .map((item) => DemoScenarioModel.fromJson(item as Map<String, dynamic>))
          .toList();
      return list;
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<DemoSeedResultModel> seedScenario(String scenarioId) async {
    try {
      final response = await apiClient.dio.post('/demo/scenarios/$scenarioId/seed');
      return DemoSeedResultModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<List<DemoSeedResultModel>> seedAllScenarios() async {
    try {
      final response = await apiClient.dio.post('/demo/seed-all');
      final list = (response.data as List)
          .map((item) => DemoSeedResultModel.fromJson(item as Map<String, dynamic>))
          .toList();
      return list;
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<DemoTamperCheckResultModel> runTamperCheck() async {
    try {
      final response = await apiClient.dio.get('/demo/audit-tamper-check');
      return DemoTamperCheckResultModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }

  Future<DemoCleanupResultModel> cleanupDemoData() async {
    try {
      final response = await apiClient.dio.post(
        '/demo/cleanup',
        data: {'confirm': true},
      );
      return DemoCleanupResultModel.fromJson(response.data as Map<String, dynamic>);
    } catch (e) {
      throw apiClient.mapDioError(e);
    }
  }
}


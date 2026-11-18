import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:insurechain_voiceguard/features/integrity/models/blockchain_status_model.dart';
import 'package:insurechain_voiceguard/features/integrity/providers/integrity_provider.dart';
import 'package:insurechain_voiceguard/features/integrity/screens/blockchain_integrity_screen.dart';
import 'package:insurechain_voiceguard/features/integrity/services/integrity_api_service.dart';

class MockIntegrityApiService extends Fake implements IntegrityApiService {
  final AuditEventVerificationModel Function(String eventId) onVerify;

  MockIntegrityApiService({required this.onVerify});

  @override
  Future<BlockchainStatusModel> getBlockchainStatus() async {
    return const BlockchainStatusModel(
      isConnected: true,
      rpcUrl: 'http://127.0.0.1:8545',
      configuredChainId: 31337,
      nodeChainId: 31337,
      blockNumber: 42,
      contractAddress: '0x5FbDB2315678afecb367f032d93F642f64180aa3',
      contractDeployed: true,
      status: 'ACTIVE',
      totalEvents: 100,
      unchainedEvents: 2,
      pendingEvents: 10,
      batchedEvents: 5,
      anchoredEvents: 80,
      failedEvents: 3,
    );
  }

  @override
  Future<AuditEventVerificationModel> verifyAuditEvent(String eventId) async {
    return onVerify(eventId);
  }

  @override
  Future<AuditEventProofModel> getAuditEventProof(String eventId) async {
    return AuditEventProofModel(
      eventId: eventId,
      sequenceNumber: 1,
      eventHash: 'a' * 64,
      batchId: 'batch-001',
      batchSequence: 1,
      batchRootHash: '0x${'b' * 64}',
      leafIndex: 0,
      merkleProof: const [],
      onChainCommitmentVerified: true,
    );
  }
}

void main() {
  group('Phase 4 Stage 4: Blockchain Integrity Screen Accuracy Tests', () {
    testWidgets('renders counters including Failed Batches and Unchained events', (tester) async {
      final mockService = MockIntegrityApiService(
        onVerify: (id) => AuditEventVerificationModel(
          eventId: id,
          outcome: 'VALID',
          message: 'Valid event',
        ),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            integrityApiServiceProvider.overrideWithValue(mockService),
          ],
          child: const MaterialApp(
            home: BlockchainIntegrityScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Anchored'), findsOneWidget);
      expect(find.text('Batched'), findsOneWidget);
      expect(find.text('Pending'), findsOneWidget);
      expect(find.text('Total Chained'), findsOneWidget);
      expect(find.text('Failed Batches'), findsOneWidget);
      expect(find.text('Unchained'), findsOneWidget);
      expect(find.text('80'), findsOneWidget); // Anchored count
      expect(find.text('3'), findsOneWidget);  // Failed Batches count
      expect(find.text('2'), findsOneWidget);  // Unchained count
    });

    testWidgets('accurately renders Blockchain Confirmed state with ON-CHAIN ANCHORED tag', (tester) async {
      final mockService = MockIntegrityApiService(
        onVerify: (id) => AuditEventVerificationModel(
          eventId: id,
          outcome: 'VALID',
          message: 'Confirmed on chain',
          onChainVerified: true,
          anchoringStatus: 'ANCHORED',
        ),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            integrityApiServiceProvider.overrideWithValue(mockService),
          ],
          child: const MaterialApp(
            home: BlockchainIntegrityScreen(initialEventId: 'evt-confirmed'),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('VALID'), findsOneWidget);
      expect(find.text('Blockchain Confirmed'), findsOneWidget);
      expect(find.text('ON-CHAIN ANCHORED'), findsOneWidget);
      expect(find.byIcon(Icons.verified_rounded), findsOneWidget);
    });

    testWidgets('accurately renders Hash-Chain Valid state for unanchored local valid event', (tester) async {
      final mockService = MockIntegrityApiService(
        onVerify: (id) => AuditEventVerificationModel(
          eventId: id,
          outcome: 'VALID',
          message: 'Hash verified locally',
          onChainVerified: false,
          anchoringStatus: 'PENDING',
        ),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            integrityApiServiceProvider.overrideWithValue(mockService),
          ],
          child: const MaterialApp(
            home: BlockchainIntegrityScreen(initialEventId: 'evt-local-valid'),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('VALID'), findsOneWidget);
      expect(find.text('Hash-Chain Valid'), findsOneWidget);
      expect(find.text('LOCAL HASH VERIFIED'), findsOneWidget);
      expect(find.byIcon(Icons.lock_outline_rounded), findsOneWidget);
      // Must NOT show on-chain anchored
      expect(find.text('ON-CHAIN ANCHORED'), findsNothing);
      expect(find.byIcon(Icons.verified_rounded), findsNothing);
    });

    testWidgets('accurately renders ANCHOR_NOT_FOUND state without green checkmark', (tester) async {
      final mockService = MockIntegrityApiService(
        onVerify: (id) => AuditEventVerificationModel(
          eventId: id,
          outcome: 'ANCHOR_NOT_FOUND',
          message: 'Batch root recorded as anchored was not found on-chain.',
          onChainVerified: false,
          anchoringStatus: 'ANCHORED',
        ),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            integrityApiServiceProvider.overrideWithValue(mockService),
          ],
          child: const MaterialApp(
            home: BlockchainIntegrityScreen(initialEventId: 'evt-not-found'),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('ANCHOR_NOT_FOUND'), findsOneWidget);
      expect(find.text('Anchor Not Found'), findsOneWidget);
      expect(find.text('ANCHOR NOT FOUND ON-CHAIN'), findsOneWidget);
      expect(find.byIcon(Icons.link_off_rounded), findsOneWidget);
      // Must never show verified checkmark or on-chain tag
      expect(find.byIcon(Icons.verified_rounded), findsNothing);
      expect(find.text('ON-CHAIN ANCHORED'), findsNothing);
    });

    testWidgets('accurately renders Verification Failed state on hash mismatch', (tester) async {
      final mockService = MockIntegrityApiService(
        onVerify: (id) => AuditEventVerificationModel(
          eventId: id,
          outcome: 'HASH_MISMATCH',
          message: 'Payload hash mismatch: fields modified.',
          onChainVerified: false,
        ),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            integrityApiServiceProvider.overrideWithValue(mockService),
          ],
          child: const MaterialApp(
            home: BlockchainIntegrityScreen(initialEventId: 'evt-mismatch'),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('HASH_MISMATCH'), findsOneWidget);
      expect(find.text('Verification Failed'), findsOneWidget);
      expect(find.text('INTEGRITY COMPROMISED'), findsOneWidget);
      expect(find.byIcon(Icons.gpp_bad_rounded), findsOneWidget);
    });
  });
}

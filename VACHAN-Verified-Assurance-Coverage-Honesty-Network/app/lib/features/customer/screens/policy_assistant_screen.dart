import 'dart:convert';
import 'dart:typed_data';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/theme/app_theme.dart';
import '../models/policy_assistant_model.dart';
import '../providers/customer_provider.dart';

class PolicyAssistantScreen extends ConsumerStatefulWidget {
  final String? policyId;
  final String? policyName;

  const PolicyAssistantScreen({
    super.key,
    this.policyId,
    this.policyName,
  });

  @override
  ConsumerState<PolicyAssistantScreen> createState() => _PolicyAssistantScreenState();
}

class _ChatMessage {
  final bool isUser;
  final String text;
  final PolicyAssistantResponseModel? assistantResponse;
  final DateTime timestamp;

  _ChatMessage({
    required this.isUser,
    required this.text,
    this.assistantResponse,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();
}

class _PolicyAssistantScreenState extends ConsumerState<PolicyAssistantScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<_ChatMessage> _messages = [];
  bool _isLoading = false;
  String? _errorMessage;

  // Audio player state
  final AudioPlayer _audioPlayer = AudioPlayer();
  int? _currentlyPlayingIndex;
  PlayerState _playerState = PlayerState.stopped;

  final List<String> _quickPrompts = [
    "What is my maximum coverage limit?",
    "What is the waiting period for pre-existing disease?",
    "Which treatments or situations are excluded?",
    "What are my room rent and ICU limits?",
    "What documents are required to file a claim?",
    "When does my policy expire?",
  ];

  @override
  void initState() {
    super.initState();

    _audioPlayer.onPlayerStateChanged.listen((state) {
      if (mounted) {
        setState(() {
          _playerState = state;
          if (state == PlayerState.completed || state == PlayerState.stopped) {
            _currentlyPlayingIndex = null;
          }
        });
      }
    });

    // Initial greeting
    _messages.add(
      _ChatMessage(
        isUser: false,
        text: widget.policyName != null
            ? "Hello! I am your AI Policy Assistant for ${widget.policyName}. I can answer questions about your coverage limits, exclusions, waiting periods, room rent, and claim requirements."
            : "Hello! I am your InsureChain Policy Assistant. Ask me anything about your registered insurance policies, coverage benefits, exclusions, or claim filing requirements.",
      ),
    );
  }

  @override
  void dispose() {
    _textController.dispose();
    _scrollController.dispose();
    _audioPlayer.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _handleSubmitted(String text) async {
    final query = text.trim();
    if (query.isEmpty || _isLoading) return;

    _textController.clear();
    setState(() {
      _messages.add(_ChatMessage(isUser: true, text: query));
      _isLoading = true;
      _errorMessage = null;
    });
    _scrollToBottom();

    try {
      final apiService = ref.read(customerApiServiceProvider);
      final response = await apiService.queryPolicyAssistant(
        question: query,
        policyId: widget.policyId,
        voiceOutput: true,
      );

      if (mounted) {
        setState(() {
          _messages.add(
            _ChatMessage(
              isUser: false,
              text: response.answer,
              assistantResponse: response,
            ),
          );
          _isLoading = false;
        });
        _scrollToBottom();

        // Auto-play response audio if available
        if (response.audioBase64 != null && response.audioBase64!.isNotEmpty) {
          _playAudio(_messages.length - 1, response.audioBase64!);
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = e.toString().replaceAll('Exception:', '').trim();
          _messages.add(
            _ChatMessage(
              isUser: false,
              text: "I encountered an error retrieving policy information. Please verify your connection and try again.",
            ),
          );
        });
        _scrollToBottom();
      }
    }
  }

  Future<void> _playAudio(int messageIndex, String audioBase64) async {
    try {
      if (_currentlyPlayingIndex == messageIndex && _playerState == PlayerState.playing) {
        await _audioPlayer.pause();
        return;
      }

      Uint8List bytes;
      if (audioBase64.contains(',')) {
        bytes = base64Decode(audioBase64.split(',')[1]);
      } else {
        bytes = base64Decode(audioBase64);
      }

      setState(() {
        _currentlyPlayingIndex = messageIndex;
      });

      await _audioPlayer.stop();
      await _audioPlayer.play(BytesSource(bytes));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Could not play spoken answer: ${e.toString()}'),
            backgroundColor: Colors.orange.shade800,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Policy Assistant',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
            ),
            if (widget.policyName != null)
              Text(
                widget.policyName!,
                style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.info_outline_rounded),
            tooltip: 'Assistant Information',
            onPressed: _showAssistantInfoDialog,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // Quick prompt chips horizontal scroll
            Container(
              height: 46,
              margin: const EdgeInsets.symmetric(vertical: 4),
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: _quickPrompts.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  final prompt = _quickPrompts[index];
                  return ActionChip(
                    label: Text(
                      prompt,
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                    ),
                    backgroundColor: AppTheme.cardWhite,
                    side: BorderSide(color: AppTheme.darkTeal.withValues(alpha: 0.2)),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                    onPressed: () => _handleSubmitted(prompt),
                  );
                },
              ),
            ),

            const Divider(height: 1, color: Color(0xFFE2E8F0)),

            // Chat Messages List
            Expanded(
              child: ListView.builder(
                controller: _scrollController,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                itemCount: _messages.length,
                itemBuilder: (context, index) {
                  final msg = _messages[index];
                  return _buildMessageItem(msg, index);
                },
              ),
            ),

            // Loading state
            if (_isLoading)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                child: Row(
                  children: [
                    Container(
                      width: 24,
                      height: 24,
                      padding: const EdgeInsets.all(2),
                      child: const CircularProgressIndicator(strokeWidth: 2, color: AppTheme.darkTeal),
                    ),
                    const SizedBox(width: 12),
                    const Text(
                      'Consulting published policy terms...',
                      style: TextStyle(fontSize: 12, color: AppTheme.textSecondary, fontStyle: FontStyle.italic),
                    ),
                  ],
                ),
              ),

            // Error banner if any
            if (_errorMessage != null)
              Container(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.red.shade50,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.red.shade200),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.error_outline, color: Colors.red, size: 18),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _errorMessage!,
                        style: const TextStyle(fontSize: 11, color: Colors.red),
                      ),
                    ),
                  ],
                ),
              ),

            // Text Input Bar
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: AppTheme.cardWhite,
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.05),
                    offset: const Offset(0, -2),
                    blurRadius: 6,
                  ),
                ],
              ),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _textController,
                      textInputAction: TextInputAction.send,
                      onSubmitted: _handleSubmitted,
                      decoration: InputDecoration(
                        hintText: 'Ask about coverage, limits, exclusions...',
                        hintStyle: const TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                        filled: true,
                        fillColor: AppTheme.background,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(24),
                          borderSide: BorderSide.none,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      color: AppTheme.darkTeal,
                    ),
                    child: IconButton(
                      icon: const Icon(Icons.send_rounded, color: Colors.white, size: 20),
                      onPressed: () => _handleSubmitted(_textController.text),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMessageItem(_ChatMessage msg, int index) {
    if (msg.isUser) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Align(
          alignment: Alignment.centerRight,
          child: Container(
            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              color: AppTheme.darkTeal,
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(16),
                topRight: Radius.circular(16),
                bottomLeft: Radius.circular(16),
                bottomRight: Radius.circular(4),
              ),
              boxShadow: [
                BoxShadow(
                  color: AppTheme.darkTeal.withValues(alpha: 0.25),
                  offset: const Offset(0, 2),
                  blurRadius: 6,
                ),
              ],
            ),
            child: Text(
              msg.text,
              style: const TextStyle(color: Colors.white, fontSize: 14, height: 1.35),
            ),
          ),
        ),
      );
    }

    final resp = msg.assistantResponse;
    final isPlaying = _currentlyPlayingIndex == index && _playerState == PlayerState.playing;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Container(
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.88),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AppTheme.cardWhite,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(16),
              topRight: Radius.circular(16),
              bottomLeft: Radius.circular(4),
              bottomRight: Radius.circular(16),
            ),
            border: Border.all(color: AppTheme.darkTeal.withValues(alpha: 0.15)),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.04),
                offset: const Offset(0, 2),
                blurRadius: 8,
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header row with Assistant Avatar and Audio Player
              Row(
                children: [
                  Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(
                      color: AppTheme.darkTeal.withValues(alpha: 0.15),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.shield_outlined, size: 16, color: AppTheme.darkTeal),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    resp?.policyName ?? 'InsureChain Policy Guard',
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
                  ),
                  const Spacer(),
                  if (resp?.audioBase64 != null)
                    IconButton(
                      icon: Icon(
                        isPlaying ? Icons.pause_circle_filled_rounded : Icons.play_circle_fill_rounded,
                        color: AppTheme.darkTeal,
                        size: 28,
                      ),
                      tooltip: isPlaying ? 'Pause spoken answer' : 'Listen to spoken answer',
                      onPressed: () => _playAudio(index, resp!.audioBase64!),
                    ),
                ],
              ),

              const SizedBox(height: 8),

              // Answer text
              Text(
                msg.text,
                style: const TextStyle(fontSize: 13.5, height: 1.45, color: Color(0xFF1E293B)),
              ),

              // Clause References if available
              if (resp != null && resp.clauseReferences.isNotEmpty) ...[
                const SizedBox(height: 10),
                const Text(
                  'GROUNDED IN POLICY CLAUSES:',
                  style: TextStyle(
                    fontSize: 9.5,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.5,
                    color: AppTheme.textSecondary,
                  ),
                ),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: resp.clauseReferences.map((clause) {
                    return Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppTheme.darkTeal.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: AppTheme.darkTeal.withValues(alpha: 0.2)),
                      ),
                      child: Text(
                        clause,
                        style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: AppTheme.darkTeal),
                      ),
                    );
                  }).toList(),
                ),
              ],

              // Footer: Grounding verification pill & Voice provider
              if (resp != null) ...[
                const SizedBox(height: 8),
                Row(
                  children: [
                    Icon(
                      resp.isGrounded ? Icons.verified_rounded : Icons.info_outline_rounded,
                      size: 13,
                      color: resp.isGrounded ? Colors.green.shade700 : Colors.amber.shade800,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      resp.isGrounded ? 'Policy-Grounded' : 'Advisory Wording',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                        color: resp.isGrounded ? Colors.green.shade700 : Colors.amber.shade800,
                      ),
                    ),
                    const Spacer(),
                    Text(
                      resp.voiceProvider == 'elevenlabs' ? 'Voice: ElevenLabs AI' : 'Voice: System Audio',
                      style: const TextStyle(fontSize: 9.5, color: AppTheme.textSecondary),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _showAssistantInfoDialog() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('About Policy Assistant'),
        content: const Text(
          'The Conversational Policy Assistant uses strict policy grounding to answer customer questions.\n\n'
          'Answers cite verbatim clauses and coverage rules from your registered policy documents. '
          'Voice synthesis is powered by ElevenLabs Text-to-Speech with deterministic offline fallback.',
          style: TextStyle(fontSize: 13, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }
}

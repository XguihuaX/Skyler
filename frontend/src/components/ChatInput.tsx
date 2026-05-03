import { useState } from 'react';
import { Ban, CornerDownLeft, Mic, Volume2, VolumeX, Sparkles } from 'lucide-react';
import { useAppStore } from '../store';
import { useAppApi } from '../contexts/appApi';
import StatusBadge from './StatusBadge';
import { setConfigField } from '../lib/window';

export default function ChatInput() {
  const [text, setText] = useState('');

  const recording    = useAppStore((s) => s.recording);
  const micMuted     = useAppStore((s) => s.micMuted);
  const status       = useAppStore((s) => s.status);
  const recordingMode = useAppStore((s) => s.recordingMode);
  const ttsEnabled   = useAppStore((s) => s.ttsEnabled);
  const currentThinking = useAppStore((s) => s.currentThinking);

  const { sendText, startManual, stopManualAndSend, toggleVad } = useAppApi();

  const handleTts = () => {
    const next = !ttsEnabled;
    useAppStore.getState().setTtsEnabled(next);
    setConfigField('tts.enabled', next).catch((e) => {
      console.error('[TTS] sync config failed:', e);
      useAppStore.getState().setTtsEnabled(!next);
    });
  };

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    sendText(trimmed);
    setText('');
  };

  const handleMic = async () => {
    if (micMuted) return;
    if (recordingMode === 'vad') {
      await toggleVad();
    } else {
      if (recording) {
        await stopManualAndSend();
      } else {
        await startManual();
      }
    }
  };

  const handleInterrupt = () => {
    // 占位行为（模块 4 语义，真实打断在 v3/v4 实装）
    useAppStore.getState().setStatus('interrupted');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      className="flex items-center gap-2 px-4 py-3 shrink-0"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        borderTop: '1px solid var(--color-border-subtle)',
      }}
    >
      <StatusBadge status={status} />

      {/* v3-F: AI 内心独白。仅当本轮收到 thinking 时显示，下一轮发送清空 */}
      {currentThinking && (
        <div
          className="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs italic max-w-[280px] overflow-hidden text-ellipsis whitespace-nowrap"
          style={{
            background: 'color-mix(in srgb, var(--color-accent) 18%, transparent)',
            color: 'var(--color-text-accent)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
          }}
          title={currentThinking}
        >
          <Sparkles size={12} className="shrink-0" />
          <span className="truncate">{currentThinking}</span>
        </div>
      )}
      {/* Interrupt — 占位，不在本模块实装 */}
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition disabled:opacity-30 disabled:cursor-not-allowed"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
          color: 'var(--color-text-secondary)',
        }}
        onClick={handleInterrupt}
        disabled={status !== 'speaking'}
        title="打断"
      >
        <Ban size={18} />
      </button>

      {/* Text field */}
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入消息…"
        className="flex-1 rounded-xl px-4 py-2 text-sm outline-none focus:ring-1"
        style={{
          background: 'var(--color-bg-input)',
          color: 'var(--color-text-primary)',
        }}
      />

      {/* Send */}
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition disabled:opacity-30 disabled:cursor-not-allowed"
        style={{
          background: text.trim() ? 'var(--color-accent)' : 'var(--color-bg-elevated)',
          color: text.trim() ? 'var(--color-bubble-user-text)' : 'var(--color-text-primary)',
        }}
        onClick={handleSend}
        disabled={!text.trim()}
        title="发送"
      >
        <CornerDownLeft size={18} />
      </button>

      {/* Mic */}
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition disabled:opacity-40 disabled:cursor-not-allowed"
        style={
          recording
            ? { background: 'var(--color-accent)', color: 'var(--color-bubble-user-text)' }
            : {
                background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
                color: 'var(--color-text-primary)',
              }
        }
        onClick={handleMic}
        disabled={micMuted}
        title={recording ? '停止录音' : '开始录音'}
      >
        <Mic size={18} />
      </button>

      {/* TTS toggle */}
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition"
        style={
          ttsEnabled
            ? {
                background: 'color-mix(in srgb, var(--color-accent) 35%, transparent)',
                color: 'var(--color-text-accent)',
              }
            : {
                background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
                color: 'var(--color-text-secondary)',
              }
        }
        onClick={handleTts}
        title={ttsEnabled ? 'TTS 已开启' : 'TTS 已关闭'}
      >
        {ttsEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
      </button>
    </div>
  );
}

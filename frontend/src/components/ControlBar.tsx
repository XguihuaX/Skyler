import { AudioWaveform, Keyboard, Mic, Settings, Volume2, VolumeX } from 'lucide-react';
import { useAppStore } from '../store';
import { useAppApi } from '../contexts/appApi';
import ConnectionDot from './ConnectionDot';
import { setConfigField } from '../lib/window';

const btnBase =
  'w-9 h-9 rounded-full backdrop-blur-md transition flex items-center justify-center';

interface ControlBarProps {
  onSettings?: () => void;
}

export default function ControlBar({ onSettings }: ControlBarProps) {
  const recording     = useAppStore((s) => s.recording);
  const micMuted      = useAppStore((s) => s.micMuted);
  const inputMode     = useAppStore((s) => s.inputMode);
  const setInputMode  = useAppStore((s) => s.setInputMode);
  const recordingMode = useAppStore((s) => s.recordingMode);
  // 2026-06-05 · "真在听" 高亮 · 跟 ChatInput 同款双源(手动→recording / VAD→vadState)。
  const vadState      = useAppStore((s) => s.vadState);
  const ttsEnabled    = useAppStore((s) => s.ttsEnabled);

  const { startManual, stopManualAndSend, toggleVad } = useAppApi();

  const handleTts = () => {
    const next = !ttsEnabled;
    useAppStore.getState().setTtsEnabled(next);
    setConfigField('tts.enabled', next).catch((e) => {
      console.error('[TTS] sync config failed:', e);
      useAppStore.getState().setTtsEnabled(!next);
    });
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

  const handleInput = () => {
    setInputMode(inputMode === 'voice' ? 'text' : 'voice');
  };

  const surfaceStyle = {
    background: 'color-mix(in srgb, var(--color-bg-surface) 70%, transparent)',
    color: 'var(--color-text-primary)',
  };

  return (
    <div className="flex items-center gap-2 justify-between">
      {/* Settings */}
      <button
        className={btnBase}
        style={surfaceStyle}
        onClick={onSettings ?? (() => console.log('settings clicked'))}
        title="设置"
      >
        <Settings size={18} />
      </button>

      {/* Microphone · 2026-06-05 · 跟 ChatInput 同款逻辑(手动=Mic,VAD=AudioWaveform;
          点亮=真在听 双源)。点击行为 handleMic 不变。 */}
      {(() => {
        const isVad = recordingMode === 'vad';
        const isListening = isVad
          ? (vadState === 'active' || vadState === 'recording')
          : recording;
        const Icon = isVad ? AudioWaveform : Mic;
        const titleListening = isVad ? '停止监听' : '停止录音';
        const titleIdle      = isVad ? '开始监听' : '开始录音';
        return (
          <button
            className={`${btnBase} ${micMuted ? 'opacity-40 cursor-not-allowed' : ''}`}
            style={isListening
              ? { background: 'var(--color-accent)', color: 'var(--color-bubble-user-text)' }
              : surfaceStyle}
            onClick={handleMic}
            disabled={micMuted}
            title={isListening ? titleListening : titleIdle}
            aria-label={isListening ? titleListening : titleIdle}
            aria-pressed={isListening}
          >
            <Icon size={18} />
          </button>
        );
      })()}

      {/* Text input toggle */}
      <button
        className={btnBase}
        style={
          inputMode === 'text'
            ? { background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }
            : surfaceStyle
        }
        onClick={handleInput}
        title={inputMode === 'text' ? '切回语音模式' : '切换到文字模式'}
      >
        <Keyboard size={18} />
      </button>

      {/* TTS toggle */}
      <button
        className={btnBase}
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

      {/* Connection indicator — not clickable */}
      <div
        className={`${btnBase} pointer-events-none cursor-default`}
        style={surfaceStyle}
      >
        <ConnectionDot />
      </div>
    </div>
  );
}

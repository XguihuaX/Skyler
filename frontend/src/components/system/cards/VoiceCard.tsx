import { useAppStore } from '../../../store';
import Card from './Card';

// silero onFrameProcessed 每 ~32ms 写一次 vadConfidence,subscribe 它的组件会
// 高频重渲染。拆到独立子组件让 parent VoiceCard 只在低频字段变化时重渲染。
function ConfidenceBar() {
  const conf = useAppStore((s) => s.vadConfidence);
  const positive = useAppStore((s) => s.vadPositiveThreshold);
  const pct = Math.max(0, Math.min(100, conf * 100));
  const threshPct = Math.max(0, Math.min(100, positive * 100));
  // 颜色:超过 positive 阈值变 accent,否则 secondary 灰。
  const barColor = conf >= positive
    ? 'var(--color-accent)'
    : 'color-mix(in srgb, var(--color-text-secondary) 60%, transparent)';
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-[11px]">
        <span style={{ color: 'var(--color-text-secondary)' }}>confidence</span>
        <span className="font-mono tabular-nums" style={{ color: 'var(--color-text-primary)' }}>
          {conf.toFixed(3)}
        </span>
      </div>
      <div className="relative h-2 rounded-full overflow-hidden"
        style={{ background: 'var(--color-bg-input)' }}>
        <div className="absolute inset-y-0 left-0 transition-[width] duration-75"
          style={{ width: `${pct}%`, background: barColor }} />
        {/* 阈值刻度线 */}
        <div className="absolute inset-y-0"
          style={{
            left: `${threshPct}%`,
            width: '2px',
            background: 'var(--color-text-accent)',
            opacity: 0.7,
          }}
          title={`positive threshold ${positive.toFixed(2)}`}
        />
      </div>
    </div>
  );
}

function vadStateColor(s: 'sleep' | 'active' | 'recording'): string {
  if (s === 'recording') return 'var(--color-accent)';
  if (s === 'active') return 'rgb(34, 197, 94)';   // green-500
  return 'color-mix(in srgb, var(--color-text-secondary) 50%, transparent)';
}

export default function VoiceCard() {
  const recordingMode = useAppStore((s) => s.recordingMode);
  const vadReady      = useAppStore((s) => s.vadReady);
  const vadState      = useAppStore((s) => s.vadState);
  const recording     = useAppStore((s) => s.recording);
  const micMuted      = useAppStore((s) => s.micMuted);
  const positive      = useAppStore((s) => s.vadPositiveThreshold);
  const redemption    = useAppStore((s) => s.vadRedemptionMs);
  const muteSpeaking  = useAppStore((s) => s.muteWhileSpeaking);

  return (
    <Card title="🎙 语音 / 录音">
      <div className="space-y-3 text-xs">
        {/* 行 1:模式 + 引擎就绪 */}
        <div className="flex items-center justify-between">
          <span style={{ color: 'var(--color-text-secondary)' }}>模式</span>
          <span
            className="px-2 py-0.5 rounded font-mono text-[11px]"
            style={{
              background: 'color-mix(in srgb, var(--color-accent) 18%, transparent)',
              color: 'var(--color-text-accent)',
            }}
          >
            {recordingMode === 'vad' ? 'VAD (自动)' : '手动'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span style={{ color: 'var(--color-text-secondary)' }}>VAD 引擎</span>
          <span style={{ color: vadReady ? 'rgb(34, 197, 94)' : 'rgb(245, 158, 11)' }}>
            {vadReady ? '✓ 就绪' : '⏳ 未就绪'}
          </span>
        </div>

        {/* 行 2:vadState badge — 间歇 bug 仪器 */}
        <div className="flex items-center justify-between">
          <span style={{ color: 'var(--color-text-secondary)' }}>VAD 状态</span>
          <span
            className="px-2 py-0.5 rounded font-mono text-[11px] uppercase"
            style={{ background: vadStateColor(vadState), color: '#fff' }}
          >
            {vadState}
          </span>
        </div>

        {/* 行 3:实时 confidence bar(子组件高频隔离)*/}
        <ConfidenceBar />

        {/* 行 4:手动录音 + mic mute */}
        <div className="flex items-center justify-between pt-1">
          <span style={{ color: 'var(--color-text-secondary)' }}>手动录音</span>
          <span style={{ color: recording ? 'var(--color-accent)' : 'var(--color-text-secondary)' }}>
            {recording ? '● 录制中' : '○ 空闲'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span style={{ color: 'var(--color-text-secondary)' }}>麦克风</span>
          <span style={{ color: micMuted ? 'rgb(245, 158, 11)' : 'var(--color-text-primary)' }}>
            {micMuted ? '🔇 静音' : '🎤 启用'}
          </span>
        </div>

        {/* 行 5:VAD 参数 */}
        <div
          className="pt-2 mt-2 grid grid-cols-3 gap-2 text-[11px]"
          style={{ borderTop: '1px dashed var(--color-border-subtle)' }}
        >
          <div>
            <div style={{ color: 'var(--color-text-secondary)' }}>positive</div>
            <div className="font-mono tabular-nums" style={{ color: 'var(--color-text-primary)' }}>
              {positive.toFixed(2)}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--color-text-secondary)' }}>redemption</div>
            <div className="font-mono tabular-nums" style={{ color: 'var(--color-text-primary)' }}>
              {(redemption / 1000).toFixed(1)} s
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--color-text-secondary)' }}>说话静音</div>
            <div style={{ color: 'var(--color-text-primary)' }}>
              {muteSpeaking ? '开' : '关'}
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}

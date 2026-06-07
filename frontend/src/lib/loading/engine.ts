// 第三刀 · sequence engine · 通用 · 吃 SequenceConfig 驱动事件流。
//
// 设计要点:
//   - 一次性 step list(at_ms 升序) · 每 tick 检查到时该 emit 的
//   - splash token 每帧 emit · UI 拿来插值任意 CSS(scale / blur / opacity)
//   - 闸 = max(floor_ms, is_ready()) · floor 到了 ready 没到 → gate-wait
//     phase · 一直 emit gate_status missing 列表 · 永不"假 100%"
//   - 单实例(每个 LoadingScreen 一个) · stop() 幂等
//
// 不依赖 React · 任意宿主都能用。

import type {
  SequenceConfig,
  SequenceEvent,
  SequencePhase,
  SequenceStep,
} from './types';

type Listener = (ev: SequenceEvent) => void;

export class SequenceEngine {
  private rafId: number | null = null;
  private t0 = 0;
  private nextIdx = 0;
  private phase: SequencePhase = 'idle';
  private listeners: Listener[] = [];
  private lastToken = -1;
  private lastMissingKey = '';

  constructor(private readonly config: SequenceConfig) {
    this.config = {
      ...config,
      steps: [...config.steps].sort((a, b) => a.at_ms - b.at_ms),
    };
  }

  on(fn: Listener): () => void {
    this.listeners.push(fn);
    return () => {
      this.listeners = this.listeners.filter((f) => f !== fn);
    };
  }

  start(): void {
    if (this.phase !== 'idle') return;
    this.t0 = performance.now();
    this.phase = 'running';
    this.emit({ kind: 'phase', phase: 'running' });
    this.tick();
  }

  stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.phase !== 'done') {
      this.phase = 'done';
      this.emit({ kind: 'phase', phase: 'done' });
    }
  }

  private emit(ev: SequenceEvent): void {
    for (const fn of this.listeners) fn(ev);
  }

  private tick = (): void => {
    if (this.phase === 'done') return;
    const elapsed = performance.now() - this.t0;
    const steps: SequenceStep[] = this.config.steps;

    while (this.nextIdx < steps.length && steps[this.nextIdx].at_ms <= elapsed) {
      for (const ev of steps[this.nextIdx].emit()) this.emit(ev);
      this.nextIdx += 1;
    }

    const tNorm = Math.min(elapsed / this.config.floor_ms, 1);
    const token = Math.min(Math.max(this.config.splash_curve(tNorm), 0), 1);
    // 只在变化 ≥ 0.005 时 emit · 省 React 重渲
    if (Math.abs(token - this.lastToken) >= 0.005 || token === 1) {
      this.lastToken = token;
      this.emit({ kind: 'splash_token', token });
    }

    if (elapsed >= this.config.floor_ms) {
      if (this.config.is_ready()) {
        // floor 满 + ready → done(token 强制冲到 1)
        if (this.lastToken < 1) {
          this.lastToken = 1;
          this.emit({ kind: 'splash_token', token: 1 });
        }
        this.phase = 'done';
        this.emit({ kind: 'phase', phase: 'done' });
        this.emit({ kind: 'done' });
        this.rafId = null;
        return;
      }
      if (this.phase !== 'gate-wait') {
        this.phase = 'gate-wait';
        this.emit({ kind: 'phase', phase: 'gate-wait' });
      }
      const missing = this.config.missing_ready();
      const key = missing.join('|');
      if (key !== this.lastMissingKey) {
        this.lastMissingKey = key;
        this.emit({ kind: 'gate_status', missing });
      }
    }

    this.rafId = requestAnimationFrame(this.tick);
  };
}

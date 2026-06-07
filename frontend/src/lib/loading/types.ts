// 第三刀 · sequence engine 通用类型。
// 之所以单独抽 engine + types · 因为 companion-loading 只是第一个 instance ·
// 后续 character-switch transition / boot-recovery 等都能复用同一套机制。

export type SequencePhase = 'idle' | 'running' | 'gate-wait' | 'done';

export type SequenceEvent =
  | { kind: 'log'; label: string; value: string }
  | { kind: 'splash_token'; token: number }
  | { kind: 'phase'; phase: SequencePhase }
  | { kind: 'gate_status'; missing: readonly string[] }
  | { kind: 'done' };

export interface SequenceStep {
  /** 相对 start() 时刻 (ms) */
  at_ms: number;
  emit: () => SequenceEvent[];
}

export interface SequenceConfig {
  name: string;
  /** 地板时长 · 即使数据/服务都 ready 也至少占满 */
  floor_ms: number;
  steps: SequenceStep[];
  /** 闸 · 返回 false 时序列在 floor 之后停 gate-wait · 直到 true 才 done */
  is_ready: () => boolean;
  /** 闸未通过时报告缺哪几路(给 UI 显真态 · 不假 100%) */
  missing_ready: () => readonly string[];
  /** splash token 曲线:t (0..1 over floor) → token (0..1) */
  splash_curve: (t: number) => number;
}

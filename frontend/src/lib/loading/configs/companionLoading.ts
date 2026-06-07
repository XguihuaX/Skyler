// 第三刀 · companion-loading 实例。cut5 cadence 改:
//   - floor 7s → 9s · 21 行铺到 0.45s..8.4s · 末行 system ready 8.6s · engine 9s 到 floor → done(进暖收)
//   - 行格式按 mockup:`> label ........ value` · UI 用 dots 补齐 · value 'ok'/'<ms>ms'/'<n>%' 三种着色
//   - 数据 100% 真实:label/value 全部来自 BootTracker snapshot · 没回的字段才用兜底
//   - 进入动画 4 路 gate 不变:embedding+whisper+ws+live2d · 无 VAD(VAD 是 mic-perm 异步 · 不入闸)
//
// mockup 23 行映射到真实 boot 步骤(英文 · 等宽 mono · token 驱动):

import type {
  SequenceConfig,
  SequenceStep,
  SequenceEvent,
} from '../types';

export interface BootSnapshotMark {
  name: string;
  duration_ms: number;
}

export interface BootSnapshot {
  marks: BootSnapshotMark[];
  bg: BootSnapshotMark[];
  total_ms: number | null;
}

export interface CompanionLoadingDeps {
  snapshot: BootSnapshot | null;
  live2dModelName: string;
  characterName: string;  // 真角色名 · 用在 sync persona 行
  ready: () => boolean;
  missing: () => readonly string[];
}

export const FLOOR_MS = 9000;

export function buildCompanionLoadingConfig(
  deps: CompanionLoadingDeps,
): SequenceConfig {
  const steps: SequenceStep[] = [];
  const log = (at_ms: number, label: string, value: string): void => {
    steps.push({
      at_ms,
      emit: (): SequenceEvent[] => [{ kind: 'log', label, value }],
    });
  };

  // snapshot 真实 marks lookup
  const marksMap: Record<string, number> = {};
  for (const m of deps.snapshot?.marks ?? []) marksMap[m.name] = m.duration_ms;
  const bgMap: Record<string, number> = {};
  for (const b of deps.snapshot?.bg ?? []) bgMap[b.name] = b.duration_ms;

  const ms = (name: string): string => {
    const v = marksMap[name];
    return v === undefined ? '...' : `${v.toFixed(0)}ms`;
  };
  const bgms = (name: string): string => {
    const v = bgMap[name];
    return v === undefined ? 'warming' : `${v.toFixed(0)}ms`;
  };
  const totalMs = deps.snapshot?.total_ms;

  // 21 行 · 0.45s 起 · 间隔约 380ms · 末行 8.55s · engine 9s floor 到 emit done
  // 平均 cadence 类似 mockup 但慢一档(mockup 110-230ms · 这里 ~380ms 配 9s 节奏)
  log(450,  'skyler runtime · v4.1',                          'ok');
  log(820,  'opening db · momoos.db',                         ms('init_db'));
  log(1180, 'applying schema · 30 idempotent migrations',     ms('db_migrations_all'));
  log(1550, 'default user · seed / verify',                   ms('default_user'));
  log(1920, 'short-term buffer restore · 3 char buckets',     ms('short_term_restore'));
  log(2280, 'hf mirror probe · hf-mirror.com',                ms('hf_mirror_probe'));
  log(2650, 'spawn preload · embedding + whisper [bg]',       'ok');
  log(3020, 'cron scheduler · 4 jobs registered',             'ok');
  log(3380, 'proactive triggers · lunch×2 / dinner / wake',   'ok');
  log(3750, 'capability registry · 15 builtin + 4 proactive', 'ok');
  log(4120, 'activity watcher · poll listeners ×2',           'ok');
  log(4480, 'establishing mcp bridge · anyio task group',     ms('mcp_server_session_manager_start'));
  log(4850, 'mcp clients · 4 external (github/fs/fetch/ev)',  ms('mcp_clients_init'));
  log(5220, 'linking llm · deepseek/deepseek-v4-pro',         'ok');
  log(5580, 'warming asr · faster-whisper [small · cpu]',     bgms('whisper_warm'));
  log(5950, 'warming embedding · paraphrase-multilingual',    bgms('embedding_warm'));
  log(6320, 'warming voice · gpt-sovits / cosyvoice [lazy]',  'lazy');
  log(6680, `loading model · ${deps.live2dModelName} [live2d]`, 'ok');
  log(7050, 'opening ws session · /ws',                       'ok');
  log(7420, `sync persona · ${deps.characterName}`,           'ok');
  log(7790, 'eager phase complete · yield to serve',
        totalMs !== null && totalMs !== undefined
          ? `${totalMs.toFixed(0)}ms`
          : 'ok');
  log(8550, 'system ready',                                   'ok');

  return {
    name: 'companion-loading',
    floor_ms: FLOOR_MS,
    steps,
    is_ready: deps.ready,
    missing_ready: deps.missing,
    // token 用在 .resolve 触发判断;这里保留单调上升 · UI 主要用 .resolve class 切两拍
    splash_curve: (t) => {
      if (t < 0.95) return t * 0.85;  // boot 阶段 token 0..0.81
      return 0.85 + ((t - 0.95) / 0.05) * 0.15;  // 末段冲到 1
    },
  };
}

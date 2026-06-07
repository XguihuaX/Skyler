// 第三刀 cut5 · React 适配层 · 把 SequenceEngine 包成 hook · 拿 boot snapshot ·
// 订阅 store 4 路 ready · 喂 buildCompanionLoadingConfig · 跑 engine ·
// 暴露 phase / token / 结构化日志(label+value) / 缺路 / done / totalSteps 给 LoadingScreen。

import { useEffect, useMemo, useRef, useState } from 'react';
import { useAppStore } from '../store';
import { SequenceEngine } from '../lib/loading/engine';
import {
  buildCompanionLoadingConfig,
  type BootSnapshot,
  type CompanionLoadingDeps,
} from '../lib/loading/configs/companionLoading';
import type { SequencePhase } from '../lib/loading/types';

const BOOT_SUMMARY_URL = 'http://127.0.0.1:8000/api/observability/boot-summary';

export interface BootLogEntry { label: string; value: string; }

export type { BootSnapshot } from '../lib/loading/configs/companionLoading';

export interface LoadingSequenceState {
  phase: SequencePhase;
  token: number;
  logs: readonly BootLogEntry[];
  missingReady: readonly string[];
  done: boolean;
  totalSteps: number;
  /** 第三刀 cut7 · 真实 boot snapshot · LoadingScreen 拿来派生 telemetry 读数
   * (EAGER ms / BG WARM ms / MIG 数 / CAP 数 等)· null = fetch 未回 */
  snapshot: BootSnapshot | null;
}

export function useLoadingSequence(): LoadingSequenceState {
  const embeddingReady = useAppStore((s) => s.embeddingReady);
  const whisperReady = useAppStore((s) => s.whisperReady);
  const wsReady = useAppStore((s) => s.wsReady);
  const live2dReady = useAppStore((s) => s.live2dReady);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const characters = useAppStore((s) => s.characters);

  const character = useMemo(
    () => characters.find((c) => c.id === currentCharacterId),
    [characters, currentCharacterId],
  );
  const live2dModelName = useMemo(() => {
    const m = character?.live2d_model?.trim();
    return m && m.length > 0 ? m : 'hiyori';
  }, [character]);
  const characterName = character?.name ?? 'momo';

  // 用 ref 给 engine 闭包读最新 ready 状态(避免 engine 重建)
  const readyRef = useRef({ embeddingReady, whisperReady, wsReady, live2dReady });
  readyRef.current = { embeddingReady, whisperReady, wsReady, live2dReady };

  const [snapshot, setSnapshot] = useState<BootSnapshot | null>(null);
  const [phase, setPhase] = useState<SequencePhase>('idle');
  const [token, setToken] = useState(0);
  const [logs, setLogs] = useState<readonly BootLogEntry[]>([]);
  const [missingReady, setMissingReady] = useState<readonly string[]>([]);
  const [done, setDone] = useState(false);
  const [totalSteps, setTotalSteps] = useState(0);

  // boot snapshot fetch · 一次性 · 失败兜底用 fallback 名(config 自己处理)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(BOOT_SUMMARY_URL);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: BootSnapshot = await res.json();
        if (!cancelled) setSnapshot(data);
      } catch (e) {
        console.warn('[loading] boot-summary fetch failed:', e);
        if (!cancelled) setSnapshot({ marks: [], bg: [], total_ms: null });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // engine 起来 · 只在 snapshot 落地后启动(snapshot=null 时 UI 显 idle)
  useEffect(() => {
    if (snapshot === null) return;
    const deps: CompanionLoadingDeps = {
      snapshot,
      live2dModelName,
      characterName,
      ready: () => {
        const r = readyRef.current;
        return r.embeddingReady && r.whisperReady && r.wsReady && r.live2dReady;
      },
      missing: () => {
        const r = readyRef.current;
        const m: string[] = [];
        if (!r.embeddingReady) m.push('embedding');
        if (!r.whisperReady) m.push('whisper');
        if (!r.wsReady) m.push('ws');
        if (!r.live2dReady) m.push('live2d');
        return m;
      },
    };
    const config = buildCompanionLoadingConfig(deps);
    setTotalSteps(config.steps.length);
    const eng = new SequenceEngine(config);
    const off = eng.on((ev) => {
      switch (ev.kind) {
        case 'log':
          setLogs((prev) => [...prev, { label: ev.label, value: ev.value }]);
          break;
        case 'splash_token':
          setToken(ev.token);
          break;
        case 'phase':
          setPhase(ev.phase);
          break;
        case 'gate_status':
          setMissingReady(ev.missing);
          break;
        case 'done':
          setDone(true);
          break;
      }
    });
    eng.start();
    return () => {
      off();
      eng.stop();
    };
    // snapshot / live2dModelName / characterName 设一次后稳定 · 不反复重建 engine
  }, [snapshot, live2dModelName, characterName]);

  return { phase, token, logs, missingReady, done, totalSteps, snapshot };
}

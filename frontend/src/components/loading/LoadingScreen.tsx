// 第三刀 cut7 · companion-loading 大窗 · Beat 1 冷赛博加厚 + Beat 2 暖揭幕不变
//
// 两拍架构(铁律:换皮不换数据):
//   1) boot(engine running · 0..9s) — 暖炭底 + 加厚赛博 HUD(角描+刻度+网格 32 呼吸
//      +扫漂+顶 telemetry+右锚 wireframe+弧 HUD+行 glyph 分层+落定 glitch+周期 RGB
//      flicker+sweep)+ 等宽英文 boot-log
//   2) resolve(engine done) — 全 HUD/网格/扫线/锚 淡出 · 暖纸光升起 · 角色 splash
//      浮入 · 标题级联 · 花瓣 · 「輕觸進入」呼吸 ← Beat 2 行为完全不变
//
// engine done = 进第②拍并停住(不 unmount) · 用户 click / keydown → fade unmount
//
// 数据保留:
//   - boot log content / telemetry 全部来自 BootTracker snapshot(真实 ms / 真名)
//   - 角色名 / live2d_model / splash 真实来自 store characters(数据库)
//   - appReady 4 路接线不变 · 只喂 engine 闸
//   - per-character theme tokens(accent / petal / 寄语)切换 · 不动数据

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useAppStore } from '../../store';
import {
  useLoadingSequence,
  type BootLogEntry,
  type BootSnapshot,
} from '../../hooks/useLoadingSequence';
import './loading.css';

const FADE_MS = 700;
const PETAL_COUNT = 14;
const LABEL_PAD_WIDTH = 46;

// 弧 HUD 几何(SVG viewBox 200x200 · 外 arc r=92)
const ARC_R = 92;
const ARC_C = 2 * Math.PI * ARC_R;   // circumference ≈ 578.05

interface Theme {
  accent: string;
  soft: string;
  glow: string;
  paper: string;
  paperDeep: string;
  petal: string;
  en: string;
  mur: string;
}

const DEFAULT_THEME: Theme = {
  accent: '#c97b8e', soft: '#e2a3b2', glow: 'rgba(216,143,160,.5)',
  paper: '#efe6db', paperDeep: '#e3d6c7', petal: '#f3c6d0',
  en: 'COMPANION', mur: '你来了。',
};

const CHARACTER_THEME: Record<number, Theme> = {
  1:   { accent: '#b08a4a', soft: '#dcc18a', glow: 'rgba(220,193,138,.5)',
         paper:  '#f1ebdd', paperDeep: '#e6dcc6', petal: '#e8d9af',
         en: 'MOMO',             mur: '你回来了。' },
  2:   { ...DEFAULT_THEME, en: 'YAE MIKO',        mur: '来得正好,我等你有一会儿了。' },
  3:   { accent: '#d4b96e', soft: '#e9d29a', glow: 'rgba(233,210,154,.5)',
         paper:  '#f1ebdd', paperDeep: '#e6dcc6', petal: '#e8d9af',
         en: 'LUMINE',           mur: '又见面了。' },
  4:   { accent: '#c6a86b', soft: '#e0c891', glow: 'rgba(224,200,145,.5)',
         paper:  '#f1ebdd', paperDeep: '#e6dcc6', petal: '#ead7a8',
         en: 'NINGGUANG',        mur: '我的时间很贵 · 望君珍惜。' },
  5:   { accent: '#88aac4', soft: '#b8d0e0', glow: 'rgba(184,208,224,.5)',
         paper:  '#e8eef2', paperDeep: '#d7e0e6', petal: '#cfe0ea',
         en: 'KAMISATO AYAKA',   mur: '不知您有何贵干?' },
  99:  { accent: '#d489a0', soft: '#ecb2c2', glow: 'rgba(236,178,194,.5)',
         paper:  '#f3e7ec', paperDeep: '#e6d2da', petal: '#f3c6d0',
         en: 'NEKO',             mur: '喵?' },
  100: { accent: '#f4a6c0', soft: '#f9c5d6', glow: 'rgba(249,197,214,.5)',
         paper:  '#f7e9ef', paperDeep: '#ecd4de', petal: '#f3c6d0',
         en: 'APHRODITE',        mur: '等你半天了。\n——这话就当我没说吧。' },
  101: { accent: '#b08a4a', soft: '#dcc18a', glow: 'rgba(220,193,138,.5)',
         paper:  '#f1ebdd', paperDeep: '#e6dcc6', petal: '#e8d9af',
         en: 'SAKURAJIMA MAI',   mur: '哦?今天倒是没迟到。' },
  102: { accent: '#3f9e96', soft: '#7fcabf', glow: 'rgba(127,202,191,.5)',
         paper:  '#e6efea', paperDeep: '#d7e6df', petal: '#cfeae2',
         en: 'FIREFLY',          mur: '要一起走完这段路吗?' },
};

interface Props { onDone: () => void; }

function classForValue(value: string): string {
  if (value === 'ok')        return 'ok';
  if (value === 'lazy')      return 'lazyv';
  if (value === 'warming')   return 'warmv';
  if (value.endsWith('%'))   return 'pctv';
  if (value.endsWith('ms'))  return 'msv';
  if (value === '...')       return 'warmv';
  return 'dots';
}

function BootLine({
  entry, isActive,
}: { entry: BootLogEntry; isActive: boolean }) {
  const dotCount = Math.max(2, LABEL_PAD_WIDTH - entry.label.length);
  const dots = '.'.repeat(dotCount);
  // ● done · ○ 当前活动(CSS blink)
  const glyph = isActive ? '○' : '●';
  return (
    <div className="ln show">
      <span className="gly">{glyph}</span>
      <span className="p">&gt;</span> <span className="label">{entry.label}</span>{' '}
      <span className="dots">{dots}</span>{' '}
      <span className={classForValue(entry.value)}>{entry.value}</span>
      {isActive && <span className="cursor" />}
    </div>
  );
}

function makePetals(count: number) {
  return Array.from({ length: count }, (_, i) => {
    const left = Math.random() * 100;
    const dur = 6 + Math.random() * 5;
    const delay = Math.random() * 6;
    const scale = 0.7 + Math.random() * 0.7;
    return (
      <div
        key={i}
        className="loading-petal"
        style={{
          left: `${left}%`,
          animationDuration: `${dur}s`,
          animationDelay: `${delay}s`,
          transform: `scale(${scale})`,
        }}
      />
    );
  });
}

/** 从真实 snapshot 派生 telemetry 读数(铁律:数据不假 · 没数据显 — 或 warming) */
function deriveTelemetry(snapshot: BootSnapshot | null) {
  const eagerMs = snapshot?.total_ms;
  const bg = snapshot?.bg ?? [];
  const bgMaxMs = bg.length > 0 ? Math.max(...bg.map((b) => b.duration_ms)) : null;
  return {
    eager: eagerMs !== null && eagerMs !== undefined ? `${eagerMs.toFixed(0)}ms` : '—',
    bg:    bgMaxMs !== null                          ? `${bgMaxMs.toFixed(0)}ms` : 'warming',
    mem:   '4 LAYERS',     // DESIGN_LITE §3:short / long / fact / rolling
    mig:   '30',           // db_migrations_all 真实 bundle 数(main.py:269-446)
    cap:   '15+4',         // 15 builtin capabilities + 4 proactive triggers(main.py:198-220)
    mcp:   '4 EXT',        // yaml mcp_clients enabled 数(github / fs / fetch / everything)
  };
}

/** 右侧 cyber anchor · SVG wireframe + 弧 HUD + crosshair + ticks */
function CyberAnchor({ progressPct }: { progressPct: number }) {
  const dash = (ARC_C * progressPct) / 100;
  // 12 个外环 tick(每 30 度一个 · 顺时针 从 12 点起)
  const ticks = Array.from({ length: 12 }, (_, i) => {
    const a = (i * 30 - 90) * (Math.PI / 180);
    const r1 = 96, r2 = 100;
    const x1 = 100 + r1 * Math.cos(a);
    const y1 = 100 + r1 * Math.sin(a);
    const x2 = 100 + r2 * Math.cos(a);
    const y2 = 100 + r2 * Math.sin(a);
    return (
      <line key={i} className="tickmark" x1={x1} y1={y1} x2={x2} y2={y2} />
    );
  });
  return (
    <div className="loading-anchor">
      <svg viewBox="0 0 200 200" aria-hidden>
        {/* 弧 HUD 背景圈(满圆 · 淡) */}
        <circle className="arc-bg" cx="100" cy="100" r={ARC_R} />
        {/* 弧 HUD 进度(从 12 点起顺时针填) */}
        <circle
          className="arc-fg"
          cx="100" cy="100" r={ARC_R}
          strokeDasharray={`${dash.toFixed(1)} ${(ARC_C - dash).toFixed(1)}`}
          transform="rotate(-90 100 100)"
        />
        {/* 12 tick marks 外环外侧 */}
        {ticks}
        {/* 中环 dashed */}
        <circle className="ring dashed" cx="100" cy="100" r="70" />
        {/* 内环 solid */}
        <circle className="ring inner"  cx="100" cy="100" r="50" />
        {/* crosshair */}
        <line className="crosshair" x1="0"   y1="100" x2="200" y2="100" />
        <line className="crosshair" x1="100" y1="0"   x2="100" y2="200" />
      </svg>
      {/* 中心 glyph(脉动) */}
      <div className="glyph">✦</div>
      <div className="pctlbl">{progressPct}%</div>
    </div>
  );
}

function AnchorTelemetry({
  embeddingReady, whisperReady, wsReady, live2dReady, progressPct,
}: {
  embeddingReady: boolean; whisperReady: boolean;
  wsReady: boolean; live2dReady: boolean; progressPct: number;
}) {
  const readyCount = [embeddingReady, whisperReady, wsReady, live2dReady].filter(Boolean).length;
  const kernelOk = progressPct >= 30;     // 30+% 行流到 cron 注册之后
  const gateReady = readyCount === 4;
  return (
    <div className="loading-anchor-tel">
      <div className="row"><span className="k">SYS</span>     <span className="v ok">AWAKE</span></div>
      <div className="row"><span className="k">KERNEL</span>  <span className={`v ${kernelOk ? 'ok' : 'pend'}`}>{kernelOk ? 'OK' : 'BOOT'}</span></div>
      <div className="row"><span className="k">GATE</span>    <span className={`v ${gateReady ? 'ok' : 'pend'}`}>{gateReady ? 'READY' : 'PEND'}</span></div>
      <div className="row"><span className="k">APPREADY</span><span className="v">{readyCount} / 4</span></div>
    </div>
  );
}

export default function LoadingScreen({ onDone }: Props) {
  const characters = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const embeddingReady = useAppStore((s) => s.embeddingReady);
  const whisperReady   = useAppStore((s) => s.whisperReady);
  const wsReady        = useAppStore((s) => s.wsReady);
  const live2dReady    = useAppStore((s) => s.live2dReady);
  // cut · engine 起步晚 3000ms · 让 boot 行 0% 起(>2.7s 门开 = preamble 已结)
  //       (0 延迟门开时 ~33% · 500 ~24% · 1500 ~14% · 3000 = 0% 起);reduce-motion 不延
  const engineStartDelayMs = useMemo(() => {
    if (typeof window === 'undefined') return 0;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 0;
    return 3000;
  }, []);
  const { phase, logs, missingReady, done, totalSteps, snapshot } =
    useLoadingSequence({ startDelayMs: engineStartDelayMs });

  const character = useMemo(
    () => characters.find((c) => c.id === currentCharacterId),
    [characters, currentCharacterId],
  );
  const theme = CHARACTER_THEME[character?.id ?? -1] ?? DEFAULT_THEME;
  const live2dModelName = character?.live2d_model?.trim() || 'hiyori';
  const splashUrl = character?.splash_art_url?.trim() || null;

  const [resolveActive, setResolveActive] = useState(false);
  const [fading, setFading] = useState(false);
  // engine done 真触发那一刻 latch 一下"加载完成"显式提示 · 然后 hold 600ms
  // 当作 Beat1→Beat2 的衔接桥 · 桥结束后 setResolveActive(true) 启动暖揭幕
  // (resolveActive 才是 Beat2 起点 · latched 只是"完成"那一帧的视觉笃定)
  const [completionLatched, setCompletionLatched] = useState(false);

  // Beat 0 · power-on preamble · 2.56s 门式揭幕(吸收进 9s floor · engine 仍从 t=0 算)
  //   curtain    0..2200ms : 全 Beat1 隐 · 0..500 dark hold / 500..1800 pivot / 1800..2560 door
  //   hud-rising 2200..2650: HUD 边框/网格/锚/顶 telemetry/brand 淡入(门正开过半)
  //   done       >=2650    : 全 Beat1 normal · 门已开 · poweron 整层 unmount
  // reduce-motion 直接落 'done' · 不演不挂 timer
  type PreambleState = 'curtain' | 'hud-rising' | 'done';
  const [preamble, setPreamble] = useState<PreambleState>(() => {
    if (typeof window === 'undefined') return 'done';
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 'done';
    return 'curtain';
  });
  useEffect(() => {
    if (preamble === 'done') return;
    const t1 = window.setTimeout(() => setPreamble('hud-rising'), 2200);
    const t2 = window.setTimeout(() => setPreamble('done'),       2650);
    return () => { window.clearTimeout(t1); window.clearTimeout(t2); };
    // 只 mount 跑一次 · preamble 自驱
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 用 ref 守一次性进入 · deps 只看 done · 不在 cleanup 里 clearTimeout —
  // 否则会触发"setCompletionLatched(true) 引发 re-render → cleanup → timer 被砍 →
  // resolveActive 永不 set"的死锁(上刀实测卡在 SYSTEM READY ✓ · regression 锁定)
  const latchedRef = useRef(false);
  useEffect(() => {
    if (!done || latchedRef.current) return;
    // engine done = 真完成(gate 通过:floor 满足 + appReady 4 路全到) · 不假完成
    // latch 笃定提示 + 600ms 桥 · 然后 resolveActive 切 Beat2
    latchedRef.current = true;
    setCompletionLatched(true);
    window.setTimeout(() => setResolveActive(true), 600);
  }, [done]);

  const dismiss = useCallback(() => {
    if (!resolveActive || fading) return;
    setFading(true);
    window.setTimeout(onDone, FADE_MS);
  }, [resolveActive, fading, onDone]);

  useEffect(() => {
    if (!resolveActive || fading) return;
    const onClick = (): void => dismiss();
    const onKey = (e: KeyboardEvent): void => {
      // 只接"明确确认"键 Enter / Space · 排除 Meta/Shift/Ctrl/Alt/Caps/方向/F* 等
      // (cut · 实测 bisect:Meta 单按曾误触 dismiss · 落地页一闪)
      if (e.key !== 'Enter' && e.key !== ' ') return;
      dismiss();
    };
    window.addEventListener('click', onClick);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('click', onClick);
      window.removeEventListener('keydown', onKey);
    };
  }, [resolveActive, fading, dismiss]);

  const progressPct = totalSteps > 0
    ? Math.min(Math.round((logs.length / totalSteps) * 100), 100)
    : 0;

  const petals = useMemo(() => makePetals(PETAL_COUNT), []);
  const telemetry = useMemo(() => deriveTelemetry(snapshot), [snapshot]);

  const themeStyle: CSSProperties = {
    ['--accent' as string]:      theme.accent,
    ['--accent-soft' as string]: theme.soft,
    ['--accent-glow' as string]: theme.glow,
    ['--paper' as string]:       theme.paper,
    ['--paper-deep' as string]:  theme.paperDeep,
    ['--petal' as string]:       theme.petal,
  };

  const winClasses = [
    'loading-win',
    resolveActive ? 'resolve' : '',
    fading ? 'fading' : '',
  ].filter(Boolean).join(' ');

  // (cut · "完成"语义改挂 completionLatched · 即 engine done 真触发 ·
  //  不再用 progressPct>=100 假完成 · 那个只是 boot-log 行数全 emit 完,
  //  跟 9s floor / appReady gate 无关。)

  return (
    <div className={winClasses} style={themeStyle} data-preamble={preamble}>
      {/* Beat 0 · power-on preamble · 双线 ±55°→交汇→门式拉开 · 1.7s · 1900ms 整层 unmount */}
      {preamble !== 'done' && (
        <div className="loading-poweron">
          <div className="poweron-half top" />
          <div className="poweron-half bottom" />
          <div className="poweron-flare" />
          <div className="poweron-line top" />
          <div className="poweron-line bottom" />
        </div>
      )}

      <div className="loading-warm" />
      <div className="loading-scan" />
      <div className="loading-sweep" />
      <div className="loading-petals">{petals}</div>
      <div className="loading-brand">MOMOOS · SKYLER</div>

      {/* cut7 · 顶部 telemetry strip(真值派生 · 6 段) */}
      <div className="loading-telemetry">
        <span className="tg"><span className="tk">EAGER</span><span className="tv">{telemetry.eager}</span></span>
        <span className="tg"><span className="tk">BG</span><span className="tv">{telemetry.bg}</span></span>
        <span className="tg"><span className="tk">MEM</span><span className="tv">{telemetry.mem}</span></span>
        <span className="tg"><span className="tk">MIG</span><span className="tv">{telemetry.mig}</span></span>
        <span className="tg"><span className="tk">CAP</span><span className="tv">{telemetry.cap}</span></span>
        <span className="tg"><span className="tk">MCP</span><span className="tv">{telemetry.mcp}</span></span>
      </div>

      {/* Beat 1 · 赛博 HUD(cut7 4 角描线 draw-in + 网格呼吸 + ticks) */}
      <div className="loading-cyberhud">
        <div className="loading-gridline" />
        <div className="loading-corner tl" />
        <div className="loading-corner tr" />
        <div className="loading-corner bl" />
        <div className="loading-corner br" />
        <div className="loading-hudlbl">BOOT.SEQ // SECURE</div>
      </div>

      {/* cut7 · 边缘 8 个 tick(2 上 / 2 下 / 2 左 / 2 右) */}
      <div className="loading-ticks">
        <span className="tick h t1" /><span className="tick h t2" />
        <span className="tick h b1" /><span className="tick h b2" />
        <span className="tick v l1" /><span className="tick v l2" />
        <span className="tick v r1" /><span className="tick v r2" />
      </div>

      {/* cut7 · 右侧 cyber anchor(wireframe + 弧 HUD + glyph)+ 下方竖排 telemetry */}
      <CyberAnchor progressPct={progressPct} />
      <AnchorTelemetry
        embeddingReady={embeddingReady} whisperReady={whisperReady}
        wsReady={wsReady} live2dReady={live2dReady}
        progressPct={progressPct}
      />

      {/* Beat 1 · boot 日志流(cut7 加 ●/○ glyph · CSS 自动分层 active/recent/trailing/old) */}
      <div className="loading-boot">
        {logs.map((entry, i) => (
          <BootLine
            key={`${i}-${entry.label}`}
            entry={entry}
            isActive={i === logs.length - 1 && !resolveActive}
          />
        ))}
      </div>

      {/* Beat 1 · 进度条 + hair line(cut7 满 100% label 翻 SYSTEM READY) */}
      <div className="loading-pbar">
        <span className={`plbl ${completionLatched ? 'latched' : ''}`}>
          {completionLatched ? '> SYSTEM READY ✓' : '> SYSTEM INITIALIZING'}
        </span>
        <div className="loading-ptrack">
          <div className="loading-pfill" style={{ width: `${progressPct}%` }} />
        </div>
        <span className="pp">{progressPct}%</span>
      </div>
      <div className="loading-hair" style={{ width: `${progressPct}%` }} />

      {/* Beat 1 · gate-wait 真态(floor 9s 满未 ready · 永不假 100%) */}
      {phase === 'gate-wait' && !resolveActive && (
        <div className="loading-gatewait">
          [gate] floor 9s 已到 · 等 ready · 还缺: {missingReady.join(', ') || '—'}
        </div>
      )}

      {/* Beat 2 · 角色 zone(splash 卡面 + 暖光晕 · 不变) */}
      <div className="loading-charzone">
        {splashUrl && (
          <img src={splashUrl} alt={character?.name ?? ''} className="splash" />
        )}
        <span className="tag">LIVE2D · {live2dModelName.toUpperCase()}</span>
      </div>

      {/* Beat 2 · 标题级联(不变) */}
      <div className="loading-title">
        <div className="b">S K Y L E R</div>
        <div className="nm">{character?.name ?? '—'}</div>
        <div className="en">{theme.en}</div>
        <div className="mur">{theme.mur}</div>
      </div>

      {/* Beat 2 · 輕觸進入(呼吸 · 不变) */}
      <div className="loading-enter"><span>輕 觸 進 入</span></div>
    </div>
  );
}

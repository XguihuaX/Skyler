import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useAppApi } from '../contexts/appApi';
import { useAppStore } from '../store';
import { useAudioAmplitude } from '../hooks/useAudioAmplitude';
import { resolveCharacterMaps } from '../lib/live2d/maps';
import { getRuntime } from '../lib/live2d/registry';
import type { Live2DRuntime, ModelHandle } from '../lib/live2d/runtime';
import {
  DEFAULT_FRAMING,
  FRAMING_SCALE_STEP,
  clampFraming,
  fetchLive2DSettings,
  type Live2DFraming,
} from '../lib/live2d/settings';

// v3-E1 step3：点击防抖窗口（毫秒）
const TOUCH_DEBOUNCE_MS = 1000;

/** 从 modelUrl(``/live2d/<slug>/<file>.model3.json``)抽 slug 作 model_key。
 *  非预期 URL(本地 file:// / 全 / 段不足)→ null · 调用方放弃 fetch settings。 */
function _slugFromModelUrl(url: string): string | null {
  // 期望:首段空(以 ``/`` 开头)· 第 2 段 "live2d" · 第 3 段 slug
  const parts = url.split('/');
  if (parts.length >= 4 && parts[0] === '' && parts[1] === 'live2d' && parts[2]) {
    return decodeURIComponent(parts[2]);
  }
  return null;
}

// v3-E1 step3：点击触发的 motion group。Hiyori 的 Tap 组下有两条 motion
// （m07 / m08），index 0/1 随机播一个。换模型时只要保留 "Tap" group 就能
// 沿用，否则在这里改 group 名。
// v3-E2：依然硬编码（per-character hitAreaMap 只决定"点哪里 → 触发什么"，
// 当前实现是 canvas 整体点击不分区域，未来 hit-area 路由接通后这两个常量
// 会被 hitAreaMap 替代）。
const TAP_MOTION_GROUP = 'Tap';
const TAP_MOTION_COUNT = 2;

interface Live2DCanvasProps {
  modelUrl: string;
  /**
   * 2026-06-17 INV · 是否应用 per-model framing(取景:scale + offset)。
   *
   * true  → 主视图 / Panel:fetch settings · 监听 pending / saved · adjustMode
   *         开时支持主画布拖拽 / 滚轮。
   * false → 小窗 / Widget:**永远 DEFAULT_FRAMING**(全身 base fit)· 跳过
   *         fetch · 不监听 pending / saved · 不响应 adjustMode 拖拽。给某模型
   *         设了 bust(scale>1 + offsetY 下移)只在主视图半身,小窗仍全身。
   */
  applyFraming: boolean;
}

/**
 * 渲染单个 Live2D Cubism 4 模型，铺满父容器。
 *
 * v3-E2 chunk 5 重构：组件不再直接 import pixi.js / pixi-live2d-display；
 * 改为通过 ``getRuntime()`` 拿 ``Live2DRuntime`` 实例，所有模型操作走接口。
 * 行为与 v3-E1 严格 1:1（idle / 触摸 Tap / motion / lip sync）。
 *
 * StrictMode 安全：
 * - cancelled flag 防御 React 18 dev 模式 mount→cleanup→mount 双跑
 * - cleanup 调 runtime.unloadModel，runtime 内部销毁 stage / 模型 / observer
 *
 * v3-G chunk 4 audit (Step Z 杂项 D-2)：dev 控制台偶见
 * "fetch hiyori_m01.motion3.json Aborted" warning，根因是 pixi-live2d-display
 * 库内部异步 fetch motion 资产时，第一轮 mount 还在加载就被 React StrictMode
 * 双 mount 触发 unloadModel 中断。**这是库行为且无害**：
 * 1. 第一轮 fetch 被 abort → console warning
 * 2. 第二轮 mount 重新 fetch → 正常完成
 * 3. idle motion 在第二轮加载完后正常播放
 * 我们的 cancelled flag + unloadModel 时序已经正确（先标 cancelled，再 unload，
 * 防止 setHandleRef 写到已 unload 的 handle 上）。warning 是库自己的 console
 * 噪音，不该追。如需消除，未来可在 PixiCubism4Runtime.unloadModel 内部对正在
 * pending 的 fetch promise 做 abort silencing —— 但代价是封装库内部行为，得不
 * 偿失。
 *
 * v3-E2 per-character 接入：
 * - 当前角色（store.currentCharacterId）经 resolveCharacterMaps 取出 motion /
 *   emotion / hitArea map。NULL / 空 / parse 失败 → 全局默认（Hiyori 不变）。
 */
export default function Live2DCanvas({ modelUrl, applyFraming }: Live2DCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // 持有 runtime 实例 + 当前 handle。runtime 实例随 mount 创建，unmount 后丢弃。
  const runtimeRef = useRef<Live2DRuntime | null>(null);
  const handleRef  = useRef<ModelHandle | null>(null);
  // 上一次成功触发触摸的时间戳，做 1 秒防抖
  const lastTouchAtRef = useRef<number>(0);

  const { sendTouch } = useAppApi();
  // v3-E1 step4：实时 TTS 振幅；驱动 ParamMouthOpenY。
  // 静默时 hook 返回 0，嘴自然闭合；v3-F 打断后 audio 队列清空，振幅也回 0。
  const amplitude = useAudioAmplitude();
  // v3-E1 step5：当轮 emotion（由后端 WS 推送，透传 LLM 原始输出）
  const currentEmotion = useAppStore((s) => s.currentEmotion);
  // v3-E1 step6：当段 motion（per-segment，每段独立解析）
  const currentMotion = useAppStore((s) => s.currentMotion);
  // 2026-06-16 INV · per-model framing 调整模式 + pending + saved。
  // pending = null 时 fallback 走 store.savedFraming(跨组件同步 · 保存后立即
  // 生效不 stale)· bisect 修:原 baseFramingRef 跨组件不同步导致保存回退到
  // mount 时旧值 · 改 store.savedFraming 后 ManagerSection 写 / Canvas 读
  // 同源 race-free。
  // applyFraming=false(widget)路径:adjustMode/pending/saved 全部 hard
  // 短路成 DEFAULT · 跳过 store subscription 避免 widget 实例被 ManagerSection
  // 改动的 store 触发重渲染。store setter 仍订阅(mount 写 saved 时用)但只在
  // applyFraming=true 时调,详 mount effect 里的 gate。
  const live2dAdjustMode_raw = useAppStore((s) => s.live2dAdjustMode);
  const pendingFraming_raw = useAppStore((s) => s.pendingFraming);
  const savedFraming_raw = useAppStore((s) => s.savedFraming);
  const setPendingFraming = useAppStore((s) => s.setPendingFraming);
  const setSavedFraming = useAppStore((s) => s.setSavedFraming);
  // gate · widget 一律 DEFAULT
  const live2dAdjustMode = applyFraming ? live2dAdjustMode_raw : false;
  const pendingFraming   = applyFraming ? pendingFraming_raw   : null;
  const savedFraming     = applyFraming ? savedFraming_raw     : null;
  // 当前 modelUrl → slug · null = 拒绝 fetch / PATCH
  const slug = useMemo(() => _slugFromModelUrl(modelUrl), [modelUrl]);
  // saved fallback:applyFraming=false → 永远 DEFAULT(全身 base fit)·
  // applyFraming=true 时按 slug 匹配走 saved。
  const fallbackFraming = useMemo<Live2DFraming>(() => {
    if (savedFraming && slug && savedFraming.modelKey === slug) {
      return savedFraming.framing;
    }
    return { ...DEFAULT_FRAMING };
  }, [savedFraming, slug]);
  // 拖拽期跟踪
  const dragStateRef = useRef<{
    pointerId: number; startX: number; startY: number;
    baseOffsetX: number; baseOffsetY: number;
  } | null>(null);
  // v3-E2：取当前角色的 maps（per-character JSON 字段优先，回退全局默认）
  const characters = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const character = useMemo(
    () => characters.find((c) => c.id === currentCharacterId) ?? null,
    [characters, currentCharacterId],
  );
  const maps = useMemo(() => resolveCharacterMaps(character), [character]);

  // 嘴型同步：每次 amplitude 变化驱动 runtime
  useEffect(() => {
    const runtime = runtimeRef.current;
    const handle  = handleRef.current;
    if (!runtime || !handle) return;
    runtime.setMouthOpen(handle, amplitude);
  }, [amplitude]);

  // emotion 视觉数据流：v3-E2 chunk 7 接通 ——
  // - emotionMap[currentEmotion] 命中 → ``runtime.setExpression(handle, name)``
  // - emotionMap 空（如 Hiyori / 八重默认 ``{}``）→ lookup miss → 无 setExpression
  //   调用，行为与 v3-E1 console.log 占位等价（无视觉变化）
  // - 角色 emotion_map_json 填充后（CharacterPanel 编辑 / 用户接入有 .exp3.json
  //   的模型时），同一 useEffect 自然激活，无需改组件代码
  useEffect(() => {
    if (!currentEmotion) return;
    const runtime = runtimeRef.current;
    const handle  = handleRef.current;
    if (!runtime || !handle) return;
    const expressionName = maps.emotionMap[currentEmotion];
    if (!expressionName) {
      // 短路：空 map / 未登记 emotion 词 → 不调 SDK（Hiyori / 八重路径）
      console.log(
        `[live2d] emotion=${currentEmotion} (no expression mapping for this character, skip)`,
      );
      return;
    }
    const ok = runtime.setExpression(handle, expressionName);
    console.log(
      `[live2d] emotion=${currentEmotion} → expression=${expressionName} ok=${ok}`,
    );
  }, [currentEmotion, maps]);

  // motion 触发：currentMotion 变化时调 runtime.startMotion
  useEffect(() => {
    if (!currentMotion) return;
    const runtime = runtimeRef.current;
    const handle  = handleRef.current;
    if (!runtime || !handle) return;
    const entry = maps.motionMap[currentMotion];
    if (!entry) {
      console.warn(`[live2d] motion="${currentMotion}" not in character motionMap, skip`);
      return;
    }
    const ok = runtime.startMotion(handle, entry.group, entry.index);
    if (ok) {
      console.log(
        `[live2d] motion=${currentMotion} → ${entry.group}[${entry.index}]`,
      );
    }
  }, [currentMotion, maps]);

  const handleTouch = useCallback(() => {
    // 2026-06-16 INV · 调整模式下点击 = 不发 touch(等同空 click)
    if (live2dAdjustMode) return;

    const now = Date.now();
    if (now - lastTouchAtRef.current < TOUCH_DEBOUNCE_MS) return;
    lastTouchAtRef.current = now;

    // 1. 立即播放 Tap motion（不等后端），让用户感知点击立刻生效。
    // v3-E2 chunk 6：per-character override —— 先查 motion_map['Tap']，命中
    // 走该角色的"点击反馈动作"（八重映射到 Start[0]）；miss 才回退 v3-E1
    // 写死的 'Tap' group + random[0,1]（Hiyori 默认 motionMap 没 'Tap' key →
    // 走回退 → 行为完全不变）。
    const runtime = runtimeRef.current;
    const handle  = handleRef.current;
    if (runtime && handle) {
      const tapEntry = maps.motionMap['Tap'];
      if (tapEntry) {
        runtime.startMotion(handle, tapEntry.group, tapEntry.index);
      } else {
        const idx = Math.floor(Math.random() * TAP_MOTION_COUNT);
        runtime.startMotion(handle, TAP_MOTION_GROUP, idx);
      }
    }

    // 2. 通知后端：本轮按 touch 事件路由（注入 system 指令 + 入对话历史）
    sendTouch();
  }, [sendTouch, maps, live2dAdjustMode]);

  // 2026-06-16 INV · framing 实时下推 runtime · pending 优先 · null 回退到
  // store.savedFraming(跟当前 slug 匹配时)· 否则 DEFAULT。
  // 依赖 fallbackFraming 一起跑:保存后 ManagerSection 写 savedFraming → 这里
  // 重跑 setFraming(new) 而不是 stale ref(bisect 修)。
  useEffect(() => {
    const runtime = runtimeRef.current;
    const handle  = handleRef.current;
    if (!runtime || !handle) return;
    const target = pendingFraming ?? fallbackFraming;
    runtime.setFraming(handle, target);
  }, [pendingFraming, fallbackFraming]);

  // 2026-06-16 INV · 调整模式下拖拽 / 滚轮事件。pointer events 防 click/touch
  // 冲突 · capture pointer 让 move/up 即使移出 canvas 也到这里。
  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!live2dAdjustMode) return;
    const cur = pendingFraming ?? fallbackFraming;
    dragStateRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      baseOffsetX: cur.offsetX,
      baseOffsetY: cur.offsetY,
    };
    try {
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    } catch { /* ignore */ }
  }, [live2dAdjustMode, pendingFraming, fallbackFraming]);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!live2dAdjustMode) return;
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    const cur = pendingFraming ?? fallbackFraming;
    setPendingFraming(clampFraming({
      scale:   cur.scale,
      offsetX: drag.baseOffsetX + dx,
      offsetY: drag.baseOffsetY + dy,
    }));
  }, [live2dAdjustMode, pendingFraming, fallbackFraming, setPendingFraming]);

  const onPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (drag && drag.pointerId === e.pointerId) {
      dragStateRef.current = null;
      try {
        (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      } catch { /* ignore */ }
    }
  }, []);

  const onWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    if (!live2dAdjustMode) return;
    // 向上滚 = 放大 · 向下滚 = 缩小(macOS 自然滚动同方向 · 触摸板 / 鼠标都 OK)
    const direction = e.deltaY < 0 ? +1 : -1;
    const cur = pendingFraming ?? fallbackFraming;
    setPendingFraming(clampFraming({
      scale:   cur.scale + direction * FRAMING_SCALE_STEP,
      offsetX: cur.offsetX,
      offsetY: cur.offsetY,
    }));
  }, [live2dAdjustMode, pendingFraming, fallbackFraming, setPendingFraming]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    const runtime = getRuntime();
    runtimeRef.current = runtime;

    (async () => {
      try {
        const handle = await runtime.loadModel(container, modelUrl);
        if (cancelled) {
          runtime.unloadModel(handle);
          return;
        }
        handleRef.current = handle;
        // 第三刀 · 喂 appReady 第 3 路(进入动画 LoadingScreen 闸 4 路之一)·
        // 静态 import 同模块单例 · 同步调用 · 不走 dynamic import(race-free)·
        // 首次 loadModel 成功 resolve 即翻 true · 后续 character switch 再 set
        // 也是 no-op(已经 true)。loadModel 失败 / cancelled / throw 都不会 set,
        // engine 仍在 gate-wait → 真实 warming 态 → 绝不假 100%。
        useAppStore.getState().setLive2dReady(true);
        // 2026-06-16 INV · 拉 per-model framing 并下推到 runtime + store。
        // 2026-06-17 · applyFraming=false(widget)→ 全程跳过 · runtime
        // ctx.framing 初值 = DEFAULT · 渲染走 base fit(全身)· 永不被主视图
        // 写的 bust framing 干扰。slug 解析失败 → 同走 default 路径。
        if (applyFraming) {
          useAppStore.getState().setPendingFraming(null);
          if (slug) {
            try {
              const s = await fetchLive2DSettings(slug);
              if (!cancelled && handleRef.current) {
                const clamped = clampFraming(s.framing);
                // 写 store:ManagerSection 保存后会改 store,Canvas useEffect
                // 监听 fallbackFraming(派生自 savedFraming)立即重渲染。
                useAppStore.getState().setSavedFraming({
                  modelKey: slug, framing: clamped,
                });
                // 这次手动直推一次:useEffect 异步 · 早一帧渲染到位防闪。
                runtime.setFraming(handleRef.current, clamped);
              }
            } catch (err) {
              console.warn('[Live2DCanvas] fetch framing failed · 走 default', err);
              useAppStore.getState().setSavedFraming(null);
            }
          } else {
            useAppStore.getState().setSavedFraming(null);
          }
        }
      } catch (err) {
        // loadModel 在 cancelled 时会自己 throw，吞掉
        if (!cancelled) {
          console.error('[Live2DCanvas] failed to load model', modelUrl, err);
        }
      }
    })();

    return () => {
      cancelled = true;
      const handle = handleRef.current;
      if (handle && runtimeRef.current) {
        runtimeRef.current.unloadModel(handle);
      }
      handleRef.current = null;
      runtimeRef.current = null;
      // 2026-06-16 INV · 切模型 / unmount 时清 pending(防上一模型未保存值
      // 跨 mount 残留)· adjustMode 由 Live2DManagerSection unmount 时关。
      // 仅 applyFraming=true 实例清 · widget 永远 null 已经,无需再清。
      if (applyFraming) {
        useAppStore.getState().setPendingFraming(null);
      }
    };
  }, [modelUrl, slug, applyFraming]);

  return (
    <div
      ref={containerRef}
      onClick={handleTouch}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onWheel={onWheel}
      className={`absolute inset-0 w-full h-full ${
        live2dAdjustMode ? 'cursor-grab' : 'cursor-pointer'
      }`}
    />
  );
}

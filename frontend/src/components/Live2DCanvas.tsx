import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useAppApi } from '../contexts/appApi';
import { useAppStore } from '../store';
import { useAudioAmplitude } from '../hooks/useAudioAmplitude';
import { resolveCharacterMaps } from '../lib/live2d/maps';
import { getRuntime } from '../lib/live2d/registry';
import type { Live2DRuntime, ModelHandle } from '../lib/live2d/runtime';

// v3-E1 step3：点击防抖窗口（毫秒）
const TOUCH_DEBOUNCE_MS = 1000;

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
 * v3-E2 per-character 接入：
 * - 当前角色（store.currentCharacterId）经 resolveCharacterMaps 取出 motion /
 *   emotion / hitArea map。NULL / 空 / parse 失败 → 全局默认（Hiyori 不变）。
 */
export default function Live2DCanvas({ modelUrl }: Live2DCanvasProps) {
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

  // emotion 视觉数据流：v3-E1 step5 起仅 console.log + 占位回调（Hiyori 没
  // .exp3.json）；v3-E3 接入有 expression 的模型时打开 setExpression 调用。
  useEffect(() => {
    if (!currentEmotion) return;
    const runtime = runtimeRef.current;
    const handle  = handleRef.current;
    if (!runtime || !handle) return;
    // 走 character emotionMap 取绑定。空 map → 没绑定，跳过；有绑定 → v3-E3
    // 这里改成根据 binding.type 走 runtime.setExpression / setParameter。
    const binding = maps.emotionMap[currentEmotion];
    if (binding == null) {
      console.log(
        `[live2d] emotion=${currentEmotion} (no binding in character emotionMap, skip)`,
      );
      return;
    }
    // 当前 binding 形态未定（v3-E3 才定形），先 console.log 占位。
    // 真正接通时改成：
    //   if (binding.type === 'expression') runtime.setExpression(handle, binding.name);
    //   else if (binding.type === 'params') binding.params.forEach(...);
    console.log(
      `[live2d] emotion=${currentEmotion} binding present but visual hookup awaits v3-E3`,
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
  }, [sendTouch, maps]);

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
    };
  }, [modelUrl]);

  return (
    <div
      ref={containerRef}
      onClick={handleTouch}
      className="absolute inset-0 w-full h-full cursor-pointer"
    />
  );
}

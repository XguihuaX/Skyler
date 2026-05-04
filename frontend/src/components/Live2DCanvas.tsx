import { useCallback, useEffect, useRef } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel, MotionPriority } from 'pixi-live2d-display/cubism4';
import { useAppApi } from '../contexts/appApi';
import { useAppStore } from '../store';
import { useAudioAmplitude } from '../hooks/useAudioAmplitude';
import { emotionMap } from '../config/live2d';

// pixi-live2d-display 内部用 window.PIXI 取 Ticker 等共享实例。必须在创建任何
// Live2DModel 之前完成挂载，否则模型的自动 ticker 不会跑（黑屏 / 不眨眼）。
(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

// v3-E1 step3：点击防抖窗口（毫秒）
const TOUCH_DEBOUNCE_MS = 1000;

// v3-E1 step3：点击触发的 motion group。Hiyori 的 Tap 组下有两条 motion
// （m07 / m08），index 0/1 随机播一个。换模型时只要保留 "Tap" group 就能
// 沿用，否则在这里改 group 名。
const TAP_MOTION_GROUP = 'Tap';
const TAP_MOTION_COUNT = 2;

// v3-E1 step4：口型同步参数。Hiyori model3.json 的 LipSync group 只有一个
// 参数 ID，主仓 0.5.0-beta 走 setParameterValueById 直写。换模型时若参数
// 名不同（比如 "PARAM_MOUTH_OPEN_Y"），改这里。
const LIPSYNC_PARAM_ID = 'ParamMouthOpenY';

// pixi-live2d-display 的 internalModel.coreModel 在类型层是 unknown 风格，
// 这里只声明我们用到的子集，避免到处 as any。
interface CubismCoreModelLipSync {
  setParameterValueById?: (id: string, value: number) => void;
}

interface Live2DCanvasProps {
  modelUrl: string;
}

/**
 * 渲染单个 Live2D Cubism 4 模型，铺满父容器。
 *
 * 行为（v3-E1 Step 2 范围）：
 * - 默认开启 idle motion 循环、自动眨眼、呼吸（pixi-live2d-display 内置）
 * - autoFocus 打开：眼睛跟随鼠标
 * - autoHitTest 关闭：触摸响应留给 Step 3
 * - contain-fit：保持模型原始宽高比，居中缩放到刚好放进容器
 * - 父容器尺寸变化（窗口 resize / Panel↔Widget 模式切换）由 ResizeObserver 监听
 *
 * StrictMode 安全：
 * - cancelled flag 防御 React 18 dev 模式 mount→cleanup→mount 双跑
 * - cleanup 会 disconnect ResizeObserver、destroy 模型、destroy PIXI Application
 */
export default function Live2DCanvas({ modelUrl }: Live2DCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // 当前活跃的 model 引用，供 onClick 调 model.motion 用。
  // 用 ref 而非 state：模型变更不应触发 React re-render。
  const modelRef = useRef<Live2DModel | null>(null);
  // 上一次成功触发触摸的时间戳，做 1 秒防抖
  const lastTouchAtRef = useRef<number>(0);

  const { sendTouch } = useAppApi();
  // v3-E1 step4：实时 TTS 振幅；驱动 ParamMouthOpenY。
  // 静默时 hook 返回 0，嘴自然闭合；v3-F 打断后 audio 队列清空，振幅也回 0。
  const amplitude = useAudioAmplitude();
  // v3-E1 step5：当轮 emotion（由后端 WS 推送，透传 LLM 原始输出）。null 表示
  // 当前没有 emotion（中性消息或新轮刚开始）。
  const currentEmotion = useAppStore((s) => s.currentEmotion);

  useEffect(() => {
    const model = modelRef.current;
    if (!model) return;
    const coreModel = model.internalModel
      ?.coreModel as unknown as CubismCoreModelLipSync | undefined;
    coreModel?.setParameterValueById?.(LIPSYNC_PARAM_ID, amplitude);
  }, [amplitude]);

  useEffect(() => {
    if (!currentEmotion) return;
    // v3-E1 step5: 仅铺数据流，不做视觉绑定（Hiyori 没有 .exp3.json，美术调参
    // 对临时模型无意义）。v3-E2 换上目标模型后这里改成：
    //   const binding = emotionMap[currentEmotion];
    //   if (binding?.type === 'expression') model.expression(binding.name);
    //   else if (binding?.type === 'params') binding.params.forEach(p =>
    //     coreModel.setParameterValueById(p.id, p.value));
    // 详见 frontend/src/config/live2d.ts emotionMap 注释。
    console.log(
      `[live2d] emotion=${currentEmotion} (no visual binding for Hiyori, awaits v3-E2)`,
    );
    // 防 unused 警告 / 让未来启用时编辑器能跳转过去
    void emotionMap;
  }, [currentEmotion]);

  const handleTouch = useCallback(() => {
    const now = Date.now();
    if (now - lastTouchAtRef.current < TOUCH_DEBOUNCE_MS) return;
    lastTouchAtRef.current = now;

    // 1. 立即播放 Tap motion（不等后端），让用户感知点击立刻生效
    const model = modelRef.current;
    if (model) {
      const idx = Math.floor(Math.random() * TAP_MOTION_COUNT);
      // motion() 返回 Promise<boolean>；忽略返回值，失败时 pixi 会在 console 自报
      void model.motion(TAP_MOTION_GROUP, idx, MotionPriority.NORMAL);
    }

    // 2. 通知后端：本轮按 touch 事件路由（注入 system 指令 + 入对话历史）
    sendTouch();
  }, [sendTouch]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    let app: PIXI.Application | null = null;
    let model: Live2DModel | null = null;
    let nativeW = 1;
    let nativeH = 1;
    let resizeObserver: ResizeObserver | null = null;

    const fit = () => {
      if (!app || !model) return;
      const w = app.renderer.width / (app.renderer.resolution || 1);
      const h = app.renderer.height / (app.renderer.resolution || 1);
      if (w <= 0 || h <= 0) return;
      const scale = Math.min(w / nativeW, h / nativeH);
      model.scale.set(scale);
      model.x = (w - nativeW * scale) / 2;
      model.y = (h - nativeH * scale) / 2;
    };

    (async () => {
      try {
        const initialW = container.clientWidth || 1;
        const initialH = container.clientHeight || 1;

        const created = new PIXI.Application({
          width: initialW,
          height: initialH,
          backgroundAlpha: 0,
          antialias: true,
          autoDensity: true,
          resolution: window.devicePixelRatio || 1,
        });
        if (cancelled) {
          created.destroy(true, { children: true, texture: true, baseTexture: true });
          return;
        }
        app = created;
        const canvas = created.view as unknown as HTMLCanvasElement;
        // PIXI 默认内联宽高样式可能反过来撑住父容器，强制让 canvas 跟父容器走
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.display = 'block';
        container.appendChild(canvas);

        const loaded = await Live2DModel.from(modelUrl, {
          autoFocus: true,
          autoHitTest: false,
        });
        if (cancelled) {
          try { loaded.destroy(); } catch { /* swallow */ }
          if (app) {
            app.destroy(true, { children: true, texture: true, baseTexture: true });
            app = null;
          }
          return;
        }
        model = loaded;
        modelRef.current = loaded;
        nativeW = loaded.width || 1;
        nativeH = loaded.height || 1;
        app.stage.addChild(loaded);
        fit();

        resizeObserver = new ResizeObserver(() => {
          if (!app) return;
          const w = container.clientWidth || 1;
          const h = container.clientHeight || 1;
          app.renderer.resize(w, h);
          fit();
        });
        resizeObserver.observe(container);
      } catch (err) {
        console.error('[Live2DCanvas] failed to load model', modelUrl, err);
      }
    })();

    return () => {
      cancelled = true;
      if (resizeObserver) {
        resizeObserver.disconnect();
        resizeObserver = null;
      }
      if (model) {
        try { model.destroy(); } catch (err) { console.warn('[Live2DCanvas] model destroy', err); }
        model = null;
      }
      modelRef.current = null;
      if (app) {
        try {
          app.destroy(true, { children: true, texture: true, baseTexture: true });
        } catch (err) {
          console.warn('[Live2DCanvas] app destroy', err);
        }
        app = null;
      }
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

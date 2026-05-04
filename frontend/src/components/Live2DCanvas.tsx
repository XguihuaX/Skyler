import { useEffect, useRef } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';

// pixi-live2d-display 内部用 window.PIXI 取 Ticker 等共享实例。必须在创建任何
// Live2DModel 之前完成挂载，否则模型的自动 ticker 不会跑（黑屏 / 不眨眼）。
(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

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
      className="absolute inset-0 w-full h-full"
    />
  );
}

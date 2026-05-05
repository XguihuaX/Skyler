// v3-E2 chunk 5：pixi-live2d-display + Cubism 4 Core 实现 Live2DRuntime。
//
// 把 v3-E1 Live2DCanvas 里全部 pixi 调用搬到这里。组件层不再 import
// pixi.js / pixi-live2d-display；只通过 Live2DRuntime 接口操作。
//
// 行为不变（与 v3-E1 严格 1:1）：
// - PIXI.Application（透明背景 / antialias / autoDensity / DPR）
// - Live2DModel.from(autoFocus: true, autoHitTest: false)
// - StrictMode 双 mount 安全：cancelled flag + 中断时 destroy 模型 + app
// - ResizeObserver 跟随父容器
// - contain-fit：保持模型原始宽高比，居中缩放
// - lip sync 写 ParamMouthOpenY；motion 走 model.motion(NORMAL)
import * as PIXI from 'pixi.js';
import {
  Live2DModel,
  MotionPriority,
  config as pixiL2DConfig,
} from 'pixi-live2d-display/cubism4';

import type { Live2DRuntime, ModelHandle } from '../runtime';

// pixi-live2d-display 内部用 window.PIXI 取 Ticker 等共享实例。必须在创建任何
// Live2DModel 之前完成挂载，否则模型的自动 ticker 不会跑（黑屏 / 不眨眼）。
// v3-E1 Live2DCanvas 顶层做的，搬到 runtime 模块顶层等价（import 时执行）。
(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

// v3-E2 patch：全局禁用 motion-bundled sound。
// 起因：BCSZ1.1（八重）motion3.json 含 ``Sound: 八重神子-X.wav`` 字段，
// pixi-live2d-display 默认看到此字段会自动播这个 wav。但 Skyler 的语音输出
// 由 LLM + TTS pipeline 统一驱动，motion 触发时 TTS 也在跑 → 双 audio
// stream 同时播 → 鬼畜重叠。
//
// pixi-live2d-display 的公开 ``model.motion(group, idx, priority)`` 接口
// 在本版本（types/index.d.ts:1692）**没有** audio 第 4 参数，无法 per-call
// 关闭。模块级 ``config.sound`` 是全局开关：设 false 后所有 model 实例的
// motion 都不再播 bundled sound。
//
// 这是阶段性方案。未来 per-character 配置（鼠标点击 vs LLM 标签区分播
// 不播 wav）见 ROADMAP backlog "Motion-bundled sound per-character toggle"。
pixiL2DConfig.sound = false;

// pixi-live2d-display 的 internalModel.coreModel 在类型层是 unknown 风格，
// 这里只声明我们用到的子集，避免到处 as any。
interface CubismCoreModelLipSync {
  setParameterValueById?: (id: string, value: number) => void;
}

// v3-E1 step4：Hiyori model3.json 的 LipSync group 单参数 ID。换模型时若
// 参数名不同（"PARAM_MOUTH_OPEN_Y" 等），用 model3.json 的 Controllers.LipSync.Items[].Id。
// 当前 Hiyori 与候选八重神子模型都是 ParamMouthOpenY，硬编码这一个值即可。
const LIPSYNC_PARAM_ID = 'ParamMouthOpenY';

interface MountContext {
  app: PIXI.Application | null;
  model: Live2DModel | null;
  nativeW: number;
  nativeH: number;
  container: HTMLElement;
  resizeObserver: ResizeObserver | null;
  cancelled: boolean;   // unloadModel 在加载未完成时翻为 true
  // v3-E2 patch：document.mouseleave / window.blur 用来把 gaze focus 拉回
  // 中央。两个 listener 注册一次，cleanup 函数同时移除两个，避免 _teardown
  // 时分散维护。
  gazeResetCleanup: (() => void) | null;
}

/**
 * pixi-live2d-display + Cubism 4 Core 的 Live2DRuntime 实现。
 *
 * 单 instance 可同时管多个 handle（理论上）；实际 v3-E2 一个 Live2DCanvas
 * 一个 handle，但 Map 模式干净，未来 split-screen / 多角色同台不会卡架构。
 */
export class PixiCubism4Runtime implements Live2DRuntime {
  readonly id = 'pixi-cubism-4';

  private contexts = new Map<string, MountContext>();
  private nextId = 1;

  async loadModel(
    container: HTMLElement,
    modelUrl: string,
  ): Promise<ModelHandle> {
    const handle: ModelHandle = { id: `pixi4-${this.nextId++}` };
    const ctx: MountContext = {
      app: null,
      model: null,
      nativeW: 1,
      nativeH: 1,
      container,
      resizeObserver: null,
      cancelled: false,
      gazeResetCleanup: null,
    };
    this.contexts.set(handle.id, ctx);

    const initialW = container.clientWidth || 1;
    const initialH = container.clientHeight || 1;

    const app = new PIXI.Application({
      width: initialW,
      height: initialH,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: window.devicePixelRatio || 1,
    });
    if (ctx.cancelled) {
      app.destroy(true, { children: true, texture: true, baseTexture: true });
      this.contexts.delete(handle.id);
      throw new Error('[live2d] loadModel cancelled before app ready');
    }
    ctx.app = app;
    const canvas = app.view as unknown as HTMLCanvasElement;
    // PIXI 默认内联宽高样式可能反过来撑住父容器，强制让 canvas 跟父容器走
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    container.appendChild(canvas);

    // React StrictMode 双 mount 时第一次加载会被 cleanup 中途取消（cancelled
    // 翻为 true 触发 destroy），pixi-live2d-display 的 MotionManager 已经并行
    // kick off 各 motion3.json 的 fetch，destroy → AbortController abort →
    // console 出现 "[MotionManager(hiyori)] Failed to load motion: ... Error:
    // Aborted"。这是 cosmetic warning，第二次 mount 后 model 完整加载所有
    // motion，idle / Tap / Flick* 全部能正常播。Step Z audit 结论保持现状。
    let loaded: Live2DModel;
    try {
      loaded = await Live2DModel.from(modelUrl, {
        autoFocus: true,
        autoHitTest: false,
      });
    } catch (err) {
      this._teardown(ctx);
      this.contexts.delete(handle.id);
      throw err;
    }
    if (ctx.cancelled) {
      try { loaded.destroy(); } catch { /* swallow */ }
      this._teardown(ctx);
      this.contexts.delete(handle.id);
      throw new Error('[live2d] loadModel cancelled mid-load');
    }
    ctx.model = loaded;
    ctx.nativeW = loaded.width || 1;
    ctx.nativeH = loaded.height || 1;
    app.stage.addChild(loaded);
    this._fit(ctx);

    // v3-E2 patch：双保险监听把 gaze focus 拉回中央。
    // pixi-live2d-display autoFocus 通过 window.mousemove 持续更新
    // ``model.focus(x, y)``，但鼠标拖出 Tauri window 后 mousemove 不再触发，
    // focus 卡在最后一个值（视线斜向某处不复位）。两条手动复位通道：
    //   - document.mouseleave：鼠标离开 viewport（拖出 window 边界）
    //   - window.blur：Tauri window 失焦（cmd+Tab / 别 app 抢焦点）
    // 二者覆盖"鼠标还在屏幕但不在 window"和"鼠标到别 app"两种场景。
    // model.focus(0, 0) 不带 instant 参数 → 平滑过渡（pixi-live2d-display
    // 内置阻尼），视觉比硬切自然。
    const handleGazeReset = (): void => {
      if (!ctx.model) return;  // _teardown 中可能已 null
      const m = ctx.model as unknown as {
        focus?: (x: number, y: number, instant?: boolean) => void;
      };
      m.focus?.(0, 0);
    };
    document.addEventListener('mouseleave', handleGazeReset);
    window.addEventListener('blur', handleGazeReset);
    ctx.gazeResetCleanup = () => {
      document.removeEventListener('mouseleave', handleGazeReset);
      window.removeEventListener('blur', handleGazeReset);
    };

    ctx.resizeObserver = new ResizeObserver(() => {
      if (!ctx.app) return;
      const w = ctx.container.clientWidth || 1;
      const h = ctx.container.clientHeight || 1;
      ctx.app.renderer.resize(w, h);
      this._fit(ctx);
    });
    ctx.resizeObserver.observe(container);

    return handle;
  }

  unloadModel(handle: ModelHandle): void {
    const ctx = this.contexts.get(handle.id);
    if (!ctx) return;
    ctx.cancelled = true;
    this._teardown(ctx);
    this.contexts.delete(handle.id);
  }

  setMouthOpen(handle: ModelHandle, value: number): void {
    const ctx = this.contexts.get(handle.id);
    const model = ctx?.model;
    if (!model) return;
    const clamped = value < 0 ? 0 : value > 1 ? 1 : value;
    const core = model.internalModel
      ?.coreModel as unknown as CubismCoreModelLipSync | undefined;
    core?.setParameterValueById?.(LIPSYNC_PARAM_ID, clamped);
  }

  startMotion(
    handle: ModelHandle,
    group: string,
    index: number,
  ): boolean {
    const ctx = this.contexts.get(handle.id);
    const model = ctx?.model;
    if (!model) return false;
    try {
      // model.motion 返回 Promise<boolean>；不 await，pixi-live2d-display
      // 失败会自己 console。返回 true 表示派发成功（不等于"动作播完"）。
      // motion-bundled sound 全局禁用（模块顶 ``pixiL2DConfig.sound = false``），
      // 避免与 TTS 重叠 —— 公开接口没 audio 4 arg，只能走全局 flag。
      void model.motion(group, index, MotionPriority.NORMAL);
      return true;
    } catch (err) {
      console.warn(
        `[live2d] startMotion("${group}", ${index}) failed:`, err,
      );
      return false;
    }
  }

  setExpression(handle: ModelHandle, name: string): boolean {
    const ctx = this.contexts.get(handle.id);
    const model = ctx?.model;
    if (!model) return false;
    // pixi-live2d-display 的 expression() 在模型没 .exp3.json 时会 console.warn
    // 并返回 false。Hiyori 是这种情况，v3-E3 接入有 expression 的模型时这条
    // 路径就有效果。这里不预先过滤，让 SDK 自己判定 + 把结果透传。
    const m = model as unknown as {
      expression?: (n: string) => boolean | Promise<boolean>;
    };
    if (typeof m.expression !== 'function') return false;
    try {
      const result = m.expression(name);
      // expression 可能同步返回 boolean 也可能返回 Promise。同步 → 直返；
      // 异步 → 派发即返 true（实际成败由 SDK console 反馈）。
      if (typeof result === 'boolean') return result;
      return true;
    } catch (err) {
      console.warn(`[live2d] setExpression("${name}") failed:`, err);
      return false;
    }
  }

  hitTest(handle: ModelHandle, x: number, y: number): string | null {
    const ctx = this.contexts.get(handle.id);
    const model = ctx?.model;
    if (!model) return null;
    const m = model as unknown as {
      hitTest?: (x: number, y: number) => string[];
    };
    if (typeof m.hitTest !== 'function') return null;
    try {
      const hits = m.hitTest(x, y);
      return hits && hits.length > 0 ? hits[0] : null;
    } catch (err) {
      console.warn(`[live2d] hitTest(${x}, ${y}) failed:`, err);
      return null;
    }
  }

  // -------------------------------------------------------------------------
  // 私有 helpers
  // -------------------------------------------------------------------------

  private _fit(ctx: MountContext): void {
    if (!ctx.app || !ctx.model) return;
    const w = ctx.app.renderer.width / (ctx.app.renderer.resolution || 1);
    const h = ctx.app.renderer.height / (ctx.app.renderer.resolution || 1);
    if (w <= 0 || h <= 0) return;
    const scale = Math.min(w / ctx.nativeW, h / ctx.nativeH);
    ctx.model.scale.set(scale);
    ctx.model.x = (w - ctx.nativeW * scale) / 2;
    ctx.model.y = (h - ctx.nativeH * scale) / 2;
  }

  private _teardown(ctx: MountContext): void {
    // 先卸 mouseleave / blur listener 再 destroy 模型 —— 否则正卡在 dispatch
    // 半路的 listener 可能拿到已销毁的 ctx.model 调 focus()。
    if (ctx.gazeResetCleanup) {
      try { ctx.gazeResetCleanup(); } catch { /* swallow */ }
      ctx.gazeResetCleanup = null;
    }
    if (ctx.resizeObserver) {
      try { ctx.resizeObserver.disconnect(); } catch { /* swallow */ }
      ctx.resizeObserver = null;
    }
    if (ctx.model) {
      try { ctx.model.destroy(); } catch (err) {
        console.warn('[live2d] model destroy', err);
      }
      ctx.model = null;
    }
    if (ctx.app) {
      try {
        ctx.app.destroy(true, { children: true, texture: true, baseTexture: true });
      } catch (err) {
        console.warn('[live2d] app destroy', err);
      }
      ctx.app = null;
    }
  }
}

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
// 2026-06-13 加 addParameterValueById(身体微晃用,跟 SDK breath/focus 同时机
// 叠加 · 在 beforeModelUpdate hook 内调)。
interface CubismCoreModelLipSync {
  setParameterValueById?: (id: string, value: number) => void;
  addParameterValueById?: (id: string, value: number) => void;
}

// pixi-live2d-display Cubism4InternalModel 继承 EventEmitter · 在 update()
// 流程内 emit 'beforeModelUpdate'(SDK cubism4.es.js:10307 · 时序:motion +
// expression + eyeBlink + focus + breath + physics + pose 全 add 完后,
// model.update() 渲染前)。是给用户注入额外参数动画的标准接口。
interface CubismInternalModelEmitter {
  on?: (event: string, listener: () => void) => void;
  off?: (event: string, listener: () => void) => void;
}

// pixi-live2d-display 的 ``model.focus(x, y)`` 与 ``focusController.focus(x, y)``
// **不是同一个坐标系**（v3-E2 patch c3b6ae2 误判踩坑后查证，下次别再错）：
//
//   - ``Live2DModel.focus(x, y, instant?)``
//     types/index.d.ts:1700-1706 docstring "Position in world space"。
//     dist/cubism4.es.js:9918 实现把 world (x,y) 经 ``toModelPosition`` 投回
//     模型本地像素，再 ``atan2 → cos,-sin`` 归一化为单位向量丢给 controller。
//     **副作用**：magnitude 恒等于 1，传 (0,0) 会被 atan2 视为 (1,0) → 头像
//     看右；传画布左上 (0,0) 会算出指向左上的单位向量。这条 API 适合"模型
//     看着鼠标光标"这种 follow-pointer 场景，不适合"复位看正前方"。
//
//   - ``FocusController.focus(x, y, instant?)``
//     types/index.d.ts:1126-1132 docstring "X position in range [-1, 1]"。
//     dist/cubism4.es.js:8013 实现是 ``targetX = clamp(x, -1, 1)`` 直写。
//     (0, 0) = 严格中央（无偏移）。这是 v3-E2 视线复位想要的语义。
//
// 复位通道用 ``model.internalModel.focusController.focus(0, 0)`` 直接走
// FocusController，绕过 Live2DModel 的 atan2 包装。
interface CubismFocusController {
  focus?: (x: number, y: number, instant?: boolean) => void;
}
interface CubismInternalModelWithFocus {
  focusController?: CubismFocusController;
}

// v3-E1 step4：Hiyori model3.json 的 LipSync group 单参数 ID。换模型时若
// 参数名不同（"PARAM_MOUTH_OPEN_Y" 等），用 model3.json 的 Controllers.LipSync.Items[].Id。
// 当前 Hiyori 与候选八重神子模型都是 ParamMouthOpenY，硬编码这一个值即可。
const LIPSYNC_PARAM_ID = 'ParamMouthOpenY';

// ---------------------------------------------------------------------------
// 转头幅度增益(2026-06-13 PM SPEC #2)
//
// 原 autoFocus: true 让 SDK 走 model.focus(x, y) → atan2 单位向量 → controller
// 满偏 → updateFocus 每帧给 ParamAngleX/Y/Z 加 ±30 度 + BodyAngleX ±10。
// 视觉是鼠标到画布边缘 = 满偏 ±30° 转头,过头。
//
// 改:autoFocus 关 · 自接 window.mousemove · 算 canvas-normalized [-1, 1] ·
// 直接调 focusController.focus(x * GAIN, -y * GAIN) · GAIN 0.5 → 满偏 ±15°。
// 现有 4 通道 gaze reset(mouseleave / blur / mouseout / mousemove clamp)
// 仍调 focusController.focus(0, 0) 复位 · 跟 GAIN 正交 · 复用不动。
//
// Y 取负 · Web 坐标 Y 向下为正 · Live2D ParamAngleY 向上为正,需翻号。
const FOCUS_GAIN = 0.5;

// ---------------------------------------------------------------------------
// 身体微晃(2026-06-13 PM SPEC #3)
//
// 给有 ParamBodyAngleY / ParamBodyAngleZ 的模型每帧叠慢速、小幅、错相的正弦
// 微动 · 视觉:身体轻微左右晃 + 微旋。BodyAngleX 不动 —— SDK breath 已经
// 用 ±4 度 / 15.5s 周期在 BodyAngleX 上跑,继续叠会过头。
//
// 缺参数 ID 的模型(神宫白子 / 秧秧 — ParamBodyAngle* 全缺)→
// addParameterValueById 对 unknown ID 是 silent no-op,自动跳过,无副作用。
//
// 振幅参考:Cubism 标准 ParamBodyAngle 范围 ±10° · 这里 ±1.5° 是保守值
// (SDK breath BodyAngleX 是 ±4° · 我们小一半,叠加视觉不像喝醉)。
// 错相周期 5.4s / 7.3s · phase 偏移 1.7 弧度 · 避免 Y/Z 同步像规则摇头。
const SWAY_BODY_Y_AMP_DEG = 1.5;
const SWAY_BODY_Z_AMP_DEG = 1.5;
const SWAY_BODY_Y_PERIOD_MS = 5400;
const SWAY_BODY_Z_PERIOD_MS = 7300;
const SWAY_BODY_Z_PHASE_RAD = 1.7;

// ---------------------------------------------------------------------------
// 冰糖模型水印关闭(2026-06-14 PM SPEC 方向修正 · 第 3 版)
//
// 真源:shuiyin1.exp3.json = { Paramheadxy:  +30, Add }
//      shuiyin2.exp3.json = { Paramheadxy3: +30, Add }
// 作者的"按 1/2 键去水印"= 应用这两个表情 = 把这 2 个参数推到 30 = 水印关。
// 也就是说 **30 = 水印关 / 0 = 水印开** · cdi3.json 那个"水印开关" Name 是
// 反义命名 / 历史遗留(用 ON 状态指代"启用水印控制器",而不是"开水印")。
//
// 前 2 版(2026-06-13 init-time set 0 + 2026-06-14 每帧 set 0)方向反 ·
// 把参数死按"水印开" · 真机看到水印属正常表现 · 不是参数错 ID。
//
// 本版实施:每帧 add 30 到这 2 个 ID(原样复刻 shuiyin1/2 表情的 Add 30)。
//   - 用 addParameterValueById 不用 setParameterValueById:跟 red.exp3 等
//     共用 Paramheadxy 的表情累加(SDK 内部会按 .moc3 烤入的 Min/Max 夹值 ·
//     即使叠加 70-90,渲染时夹回上限,不会爆值)· red 的几何效果保留。
//   - 只动 2 个 ID:Paramheadxy / Paramheadxy3。前版多带 Paramheadxy2/4/5/6
//     是过度防御(那 4 个没人在 expressions 用,默认状态是什么不清楚 · 不再
//     主动干预,避免破坏没必要碰的字段)。
//   - 其它模型(没这俩 ID)addParameterValueById 静默 no-op · 无副作用。
//
// hook 时机:onBeforeModelUpdate(SDK 所有 motion / expression / breath /
// focus 跑完后,model.update 渲染前)· 累加在所有 system 之上。
//
// 若真机还看到部分水印行字 → 那部分不是 Paramheadxy/3 控的,转向查 4 张
// texture / Part Opacity(本轮先不动贴图,按 SPEC 真机判别结果再说)。
const BINGTANG_WATERMARK_OFF_PARAM_IDS: readonly string[] = [
  'Paramheadxy',
  'Paramheadxy3',
];
const BINGTANG_WATERMARK_OFF_VALUE = 30;

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
  // 2026-06-13 SPEC #3 身体微晃 cleanup —— off internalModel.on('beforeModelUpdate')
  swayCleanup: (() => void) | null;
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
      swayCleanup: null,
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
      // 2026-06-13 SPEC #2:autoFocus 改 false · 自接 mousemove + GAIN clamp ·
      // 见 _attachManualFocus(下) + FOCUS_GAIN 模块顶常量。
      loaded = await Live2DModel.from(modelUrl, {
        autoFocus: false,
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

    // 2026-06-13 SPEC #1+#3 · 单 beforeModelUpdate hook 复用两件事:
    //   1. 冰糖水印 6 个 Paramheadxy* 每帧强制 setParameterValueById 0
    //      (init-time 一次性 set 真机失败 · 见模块顶 BINGTANG_WATERMARK_*
    //      docstring · 原因:.moc3 default 可能非 0 + SDK save/load 时序错位 ·
    //      hook 时机 = SDK 所有 system add 完后,model.update 渲染前)
    //   2. 身体微晃:有 ParamBodyAngleY/Z 的模型 add 慢速正弦小幅微动
    //      (BodyAngleX 不动 · SDK breath 已经在那里跑 ±4° / 15.5s · 续叠会过头)
    //
    // 缺参数 ID 的模型(神宫白子 / 秧秧 — ParamBodyAngle*;非冰糖 — 6 个
    // Paramheadxy*)→ setParameterValueById / addParameterValueById 对 unknown
    // ID 是 silent no-op,自动跳过,无副作用。不需要前置探测/分支判断。
    const swayStartT = performance.now();
    const swayCore = loaded.internalModel
      ?.coreModel as unknown as CubismCoreModelLipSync | undefined;
    const onBeforeModelUpdate = (): void => {
      if (!swayCore?.addParameterValueById) return;
      // ---- 冰糖水印关:每帧 add 30 复刻 shuiyin1/2 表情 ----
      // 用 add 不用 set:跟 red.exp 等共用 Paramheadxy 的表情累加 ·
      // SDK 按 .moc3 烤入的 Min/Max 夹值 · 不爆值不抹其他表情几何效果。
      // 其它模型没这俩 ID → silent no-op。
      for (const id of BINGTANG_WATERMARK_OFF_PARAM_IDS) {
        swayCore.addParameterValueById(id, BINGTANG_WATERMARK_OFF_VALUE);
      }
      // ---- 身体微晃 ----
      const t = performance.now() - swayStartT;
      const y = SWAY_BODY_Y_AMP_DEG *
        Math.sin((2 * Math.PI * t) / SWAY_BODY_Y_PERIOD_MS);
      const z = SWAY_BODY_Z_AMP_DEG *
        Math.sin(
          (2 * Math.PI * t) / SWAY_BODY_Z_PERIOD_MS + SWAY_BODY_Z_PHASE_RAD,
        );
      swayCore.addParameterValueById('ParamBodyAngleY', y);
      swayCore.addParameterValueById('ParamBodyAngleZ', z);
    };
    const swayEmitter = loaded.internalModel as unknown as
      CubismInternalModelEmitter | undefined;
    if (swayEmitter?.on && swayEmitter?.off) {
      swayEmitter.on('beforeModelUpdate', onBeforeModelUpdate);
      ctx.swayCleanup = () => swayEmitter.off?.('beforeModelUpdate', onBeforeModelUpdate);
    }

    // 2026-06-13 SPEC #2 · 自接 window.mousemove + GAIN(autoFocus 已关 · 上面 Live2DModel.from 第二参数)。
    // canvas-normalized [-1, 1] · 鼠标在画布中心 → 焦点 (0, 0) · 鼠标到画布
    // 边缘 → 焦点 ±1 · 经 GAIN 0.5 → controller ±0.5 → SDK updateFocus 内
    // 按 ×30 倍率 → ParamAngleX/Y 满偏 ±15°。
    //
    // 复用现有 4 通道 gaze reset(下方代码块) — 它们调 focusController.focus(0, 0)
    // 复位,跟 GAIN 正交,继续工作:
    //   - mouseleave / blur / mouseout / mousemove 越界 clamp
    //
    // 坐标:Y 取负 · web 向下为正 · Live2D ParamAngleY 向上为正。
    const handleManualFocus = (e: MouseEvent): void => {
      if (!ctx.model) return;
      const rect = canvas.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = ((e.clientY - rect.top) / rect.height) * 2 - 1;
      // 鼠标越界由下方 mousemove clamp 路径捕到 + reset · 这里不处理 ·
      // 让 gazeReset 那条链统一管 reset 行为。
      if (x < -1 || x > 1 || y < -1 || y > 1) return;
      const internal = ctx.model.internalModel as unknown as
        CubismInternalModelWithFocus | undefined;
      internal?.focusController?.focus?.(x * FOCUS_GAIN, -y * FOCUS_GAIN);
    };
    window.addEventListener('mousemove', handleManualFocus);

    // v3-E2 patch：把 gaze focus 拉回中央，覆盖鼠标离开 webview 的所有场景。
    // pixi-live2d-display autoFocus 通过 window.mousemove 持续更新
    // ``model.focus(x, y)``，但鼠标拖出 Tauri window 后 mousemove 不再触发，
    // focus 卡在最后一个值（视线斜向某处不复位）。
    //
    // 四层监听（互不替代，叠加触发）：
    //
    // 标准浏览器（W3C）路径 ——
    //   1. document.mouseleave：鼠标离开整个 viewport
    //   2. window.blur：window 失焦（cmd+Tab）
    //
    // macOS Tauri (WKWebView) 实测兜底（commit 0cd4fa5 后用户验证 1/2 都不
    // 触发，必须加另外两条）——
    //   3. document.mouseout (relatedTarget === null)：鼠标离开整个 document，
    //      须 filter relatedTarget 否则 element 间转移也触发会让视线乱跳
    //   4. window.mousemove 坐标 clamp：缓慢滑到边缘时 mouseout 也可能不触发，
    //      检查 e.client{X,Y} 越界即复位
    //
    // 保留 1/2 是因为它们在标准浏览器仍 work，未来 Tauri 升级修了这个 webview
    // bug / 切到 Electron / 项目嵌别的 host 时不返工。3/4 是 macOS Tauri 实测
    // 可靠的兜底。
    //
    // 复位走 ``focusController.focus(0, 0)`` 不走 ``model.focus(0, 0)`` ——
    // 文件头注释记录了两者坐标系差异。controller 的 (0, 0) 才是严格中央。
    // 不传 instant → 平滑过渡（pixi-live2d-display 内部阻尼），视觉比硬切
    // 自然。重复调用幂等。
    const handleGazeReset = (): void => {
      if (!ctx.model) return;  // _teardown 中可能已 null
      const internal = ctx.model.internalModel as unknown as
        CubismInternalModelWithFocus | undefined;
      internal?.focusController?.focus?.(0, 0);
    };
    const handleMouseOut = (e: MouseEvent): void => {
      // relatedTarget === null 是"鼠标离开整个 document"的可靠判断；
      // 如果是 element → element 转移，relatedTarget 是新 element，跳过。
      if (e.relatedTarget !== null) return;
      handleGazeReset();
    };
    const handleMouseMove = (e: MouseEvent): void => {
      // mousemove 高频事件：4 次数值比较 + early-out，性能可忽略。
      // 在 viewport 内时直接 return，只有越界（鼠标拖到边缘 / 跨界瞬间）
      // 才触发 reset。
      if (
        e.clientX < 0 || e.clientX > window.innerWidth ||
        e.clientY < 0 || e.clientY > window.innerHeight
      ) {
        handleGazeReset();
      }
    };
    document.addEventListener('mouseleave', handleGazeReset);
    window.addEventListener('blur', handleGazeReset);
    document.addEventListener('mouseout', handleMouseOut);
    window.addEventListener('mousemove', handleMouseMove);
    ctx.gazeResetCleanup = () => {
      document.removeEventListener('mouseleave', handleGazeReset);
      window.removeEventListener('blur', handleGazeReset);
      document.removeEventListener('mouseout', handleMouseOut);
      window.removeEventListener('mousemove', handleMouseMove);
      // 2026-06-13 SPEC #2 · 自接 mousemove 同一时段注册同一时段卸,放一起统一管。
      window.removeEventListener('mousemove', handleManualFocus);
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
    // 2026-06-13 SPEC #3 · 身体微晃 hook off · internalModel emit
    // 路径,跟 mousemove 是不同来源,单独 cleanup。
    if (ctx.swayCleanup) {
      try { ctx.swayCleanup(); } catch { /* swallow */ }
      ctx.swayCleanup = null;
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

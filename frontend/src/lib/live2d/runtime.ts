import type { Live2DFraming } from './settings';

// v3-E2 chunk 5：Live2D 运行时抽象层。
//
// 让组件层（Live2DCanvas）跟具体 SDK（pixi-live2d-display / Cubism Web SDK
// 5 / cubism2-runtime）解耦：组件只持有 ModelHandle + 调 Runtime 接口，
// 切换 SDK 时改 RuntimeRegistry 的工厂返回，不动组件。
//
// 现有 v3-E1 全部行为保留：
// - idle / 眨眼 / 呼吸 由 SDK 内置（loadModel 时配置）
// - 口型同步：setMouthOpen(value 0~1)
// - LLM motion：startMotion(group, index)
// - LLM emotion：setExpression(name)，Hiyori 没 .exp3.json 时返回 false
// - 触摸：组件层 onClick 拿到 local 坐标后调 hitTest，返回 hit area 名
//   （v3-E1 并未启用 hit area 路由，先把契约准备好供 v3-E2 / E3 接通）

/**
 * Runtime 内部追踪每次 loadModel 的私有上下文（PIXI app / 模型实例 /
 * resize observer）。组件只持有不透明 handle，把它传回各调用即可。
 */
export interface ModelHandle {
  readonly id: string;
}

export interface Live2DRuntime {
  /** 实现标识，便于 debug + 未来 RuntimeRegistry 选型日志 */
  readonly id: string;

  /**
   * 在 ``container`` 中创建 stage 并加载模型。
   *
   * 完整接管：插入 canvas、loadModel、addChild、初次 fit、装 ResizeObserver
   * 跟随父尺寸。返回 ``ModelHandle`` 供后续操作。
   *
   * 调用方需保证 ``container`` 为已挂载到 DOM 的 HTMLElement，宽高 > 0。
   * 加载过程中调 ``unloadModel(handle)`` 立即中断（StrictMode 双 mount
   * 时第一次的 mount 会被 cleanup 中断）。
   */
  loadModel(container: HTMLElement, modelUrl: string): Promise<ModelHandle>;

  /**
   * 释放 stage / 模型 / observer / canvas DOM 节点。幂等。
   * 即使 loadModel 在加载途中被取消，对未完成的 handle 也安全。
   */
  unloadModel(handle: ModelHandle): void;

  /**
   * 嘴型同步。``value`` ∈ [0, 1]，超出会被 clamp。每帧调用安全。
   * 模型尚未加载完时静默 no-op。
   */
  setMouthOpen(handle: ModelHandle, value: number): void;

  /**
   * 触发动作。返回是否成功派发（group 不存在 / index 越界 → false）。
   * 优先级语义由实现决定，pixi-live2d-display 当前用 NORMAL，与触摸点击
   * 同级，先到先服务。
   */
  startMotion(handle: ModelHandle, group: string, index: number): boolean;

  /**
   * 触发表情（Live2D expression）。Hiyori 没 .exp3.json 时返回 false。
   * v3-E3 emotion 视觉绑定真接入时开始有用。
   */
  setExpression(handle: ModelHandle, name: string): boolean;

  /**
   * Hit-test：local 像素坐标 → hit area 名（若有）。
   * v3-E1 未启用，先把契约准备好；v3-E2 接入八重神子 8 个 HitAreas 时用。
   */
  hitTest(handle: ModelHandle, x: number, y: number): string | null;

  /**
   * 2026-06-16 INV · per-model framing(取景)叠加在 base fit 之上。
   *
   * base 不动:`_fit` 仍算 `min(w/nativeW, h/nativeH)` 居中(承接 ResizeObserver
   * 父容器变化)· framing 是其上的乘 + 加。**叠加 · 不替换 base**。
   *
   * 调用方时机:mount 完成后(读 DB 拿 framing)/ 用户调滑块 / 拖拽 / 滚轮 ·
   * 频率高(拖拽时 ~60Hz)· 实现只改 ctx.framing 后重调 `_fit` · 单次 O(1)。
   *
   * 模型尚未加载完时静默 no-op(同 setMouthOpen 规范)。
   */
  setFraming(handle: ModelHandle, framing: Live2DFraming): void;
}

/** Re-export 给 runtime 实现 + 组件层共用。真源在 ``lib/live2d/settings.ts``。 */
export type { Live2DFraming } from './settings';

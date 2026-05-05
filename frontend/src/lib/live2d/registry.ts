// v3-E2 chunk 5：RuntimeRegistry 工厂入口。
//
// 当前只有 PixiCubism4Runtime 一个实现，所以工厂逻辑非常简单。设这层是
// 为了未来：
// - Cubism 5 fork（社区目前在做 pixi-live2d-display 的 Cubism 5 patch）
//   接通后，按 ``moc3_version >= 5`` 走另一个 runtime
// - Cubism 2 / .moc 文件想接通时，按"无 .moc3 / 有 .moc"分支走 cubism2-runtime
//
// 工厂返回新实例（不是 singleton）—— 每个 Live2DCanvas 一个 runtime，
// 销毁时 unloadModel + 实例自然 GC，避免跨组件 contexts Map 泄漏。

import type { Live2DRuntime } from './runtime';
import { PixiCubism4Runtime } from './runtimes/pixiCubism4';

/**
 * 选取适合该模型的 Runtime 实现。
 *
 * @param hint 可选；若未来扩成多 runtime，传 ``moc3_version`` 走分支。
 *             v3-E2 当前忽略，单一实现命中。
 * @returns 一个新创建的 Runtime 实例。调用方负责 unloadModel 后丢弃引用。
 */
export function getRuntime(
  hint?: { moc3_version?: number | null },
): Live2DRuntime {
  // 当前唯一实现：pixi-live2d-display + Cubism 4 Core，moc3 ver ≤ 4。
  // moc3 ver >= 5 时本应换 Cubism 5 runtime；目前社区无可用 fork（issue #118
  // 自 2023-10 未修复），所以 ver >= 5 也只能落这里 + console.warn 提示。
  if (hint?.moc3_version != null && hint.moc3_version > 4) {
    console.warn(
      `[live2d] moc3 version ${hint.moc3_version} > 4 (Cubism 5);` +
      ' no compatible runtime, falling back to pixi-live2d-display' +
      ' which will likely fail to render. Track GitHub pixi-live2d-display#118.',
    );
  }
  return new PixiCubism4Runtime();
}

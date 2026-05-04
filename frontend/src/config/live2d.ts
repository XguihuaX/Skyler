// v3-E1: 把 character.live2d_model（用户在 CharacterPanel 填写的目录名）映射到
// 该模型目录下实际的 model3.json 入口文件。每个 Live2D 模型的 model3.json
// 文件名由作者决定，没法靠目录名推断，所以维护一个显式 map。
//
// 加新模型时：
//   1. 把模型资产放到 frontend/public/live2d/<name>/
//   2. 在这里登记 <name> -> "<actual>.model3.json"
//   3. CharacterPanel 里给角色填上 <name>

export const live2dModelEntry: Record<string, string> = {
  hiyori: 'hiyori_pro_t11.model3.json',
};

export function resolveLive2dModelUrl(
  modelName: string | null | undefined,
): string | null {
  if (!modelName) return null;
  const entry = live2dModelEntry[modelName];
  if (!entry) {
    console.warn(`[live2d] unknown model name: ${modelName}, fallback to image`);
    return null;
  }
  return `/live2d/${modelName}/${entry}`;
}

// ---------------------------------------------------------------------------
// v3-E1 step5: emotion → Live2D 视觉绑定占位
//
// 当前空实现 —— 本步只铺了 emotion 数据流（后端 _parse_emotion → WS push →
// store.currentEmotion → Live2DCanvas useEffect 监听点），不做 Hiyori 上的
// 视觉绑定。原因：
//   1. Hiyori 模型 .model3.json 没有 FileReferences.Expressions 字段
//      （没有 .exp3.json 文件）—— model.expression() 调不动。
//   2. 用 setParameterValueById 组合参数模拟表情可行，但这种"美术调参"
//      只对 Hiyori 这个临时模型有意义，v3-E2 换上目标模型后大概率失效。
//   3. 数据流先铺好，未来换模型只改这个 map 一个文件，Live2DCanvas
//      监听点的代码不动。
//
// v3-E2 / v3-E3 换模型后填充策略：
// (a) 模型自带 .exp3.json：
//     emotionMap[key] = { type: 'expression', name: 'F01' }
//     Live2DCanvas 调 model.expression(map.name)
// (b) 模型无 expression 文件，自制参数偏移：
//     emotionMap[key] = { type: 'params', params: [{ id: 'ParamMouthForm', value: 1.0 }, ...] }
//     Live2DCanvas 遍历 params 调 setParameterValueById
//
// key 是 LLM 原始输出（透传，不归一化）：happy / sad / angry / surprised /
// fearful / disgusted / 等。完整列表见 config.yaml emotions。
// ---------------------------------------------------------------------------

export const emotionMap: Record<string, unknown> = {
  // v3-E2 填充
};

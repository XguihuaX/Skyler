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

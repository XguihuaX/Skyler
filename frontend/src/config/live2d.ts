// v3-E1: 把 character.live2d_model（用户在 CharacterPanel 填写的目录名）映射
// 到该模型目录下实际的 model3.json 入口文件。每个 Live2D 模型的 model3.json
// 文件名由作者决定，没法靠目录名推断。
//
// v3-E2 chunk 3：scanner 后端 (GET /api/live2d/models) 自动读 model3.json
// 返回 model3_path —— 不再需要前端手维护字典。本文件保留 hardcode 字典
// 仅作"scanner 不可达 / store 还没填充"时的兜底，以及一个无网络的离线
// 默认（Hiyori）。
//
// 加新模型时：
//   1. 把模型资产放到 frontend/public/live2d/<name>/
//   2. CharacterPanel 里给角色填上 <name>
//   3. （可选）若想离线兜底，在 live2dModelEntry 里登记 <name> -> 入口
//      文件名；scanner 工作时不需要这一步

import type { Live2DModel } from '../lib/live2d';

export const live2dModelEntry: Record<string, string> = {
  hiyori: 'hiyori_pro_t11.model3.json',
};

/**
 * 解析 character.live2d_model（slug）到 Vite 静态 URL。
 *
 * 优先级：
 *   1. scanner store（``models``）按 slug 命中 → 用 ``model3_path``
 *   2. ``live2dModelEntry`` hardcode 命中 → 拼 ``/live2d/<slug>/<file>``
 *   3. 都 miss → null + console.warn，CharacterView 回退静态图
 *
 * scanner 命中时不读 hardcode（即便 hardcode 也有该 slug）—— scanner 是
 * 唯一真相源，hardcode 只在 scanner 数据没到时兜底。
 *
 * @param modelName slug，等于 ``frontend/public/live2d/<slug>/`` 目录名
 * @param models    可选；scanner store 的 ``live2dModels``。不传 / 空数组
 *                  时直接走 hardcode 兜底（启动早期 / 离线 / API 报错场景）
 */
export function resolveLive2dModelUrl(
  modelName: string | null | undefined,
  models?: readonly Live2DModel[],
): string | null {
  if (!modelName) return null;

  // 1. Scanner-first
  if (models && models.length > 0) {
    const scanned = models.find((m) => m.slug === modelName);
    if (scanned && scanned.model3_path) {
      return scanned.model3_path;
    }
  }

  // 2. Hardcode fallback —— scanner 不可达或还没填充时用
  const entry = live2dModelEntry[modelName];
  if (entry) {
    if (models && models.length > 0) {
      // scanner 列出来了但没这个 slug + hardcode 有 → 数据不一致，告警但仍走兜底
      console.warn(
        `[live2d] slug "${modelName}" not in scanner result, using hardcode fallback`,
      );
    }
    return `/live2d/${modelName}/${entry}`;
  }

  // 3. 都没有 → 让 CharacterView 回退静态图
  console.warn(`[live2d] unknown model name: ${modelName}, fallback to image`);
  return null;
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

// v3-E2 chunk 7：emotionMap value 类型确定为 ``string`` —— 即"emotion 词
// → Live2D expression 名"，runtime.setExpression 直接吃这个值。
//
// 全局默认仍留空 ``{}`` —— v3-E1 内置的 Hiyori 没 .exp3.json，无 expression
// 可绑；任何 emotion 词查询本表都会 miss，Live2DCanvas useEffect 走"无绑定
// 短路 console.log"分支，行为与 v3-E1 完全一致。
//
// per-character emotion_map_json 写实际内容时（如 8 重神子未来加 mod 添
// expression、或换上自带 .exp3.json 的目标模型），CharacterPanel 编辑后
// resolveCharacterMaps 优先取 character 字段，本默认只在该字段 NULL / 坏
// JSON 时兜底。
export const emotionMap: Record<string, string> = {};

// ---------------------------------------------------------------------------
// v3-E1 step6: motion → Live2D model.motion(group, index, priority) 映射
//
// LLM 在回复中用 <motion>X</motion> 标签嵌入动作；后端 _parse_motion 抽出
// 中文名 X 推到前端 store.currentMotion，Live2DCanvas useEffect 通过本 map
// 查 group/index 调 model.motion()。
//
// Hiyori (hiyori_pro_t11) motion 资源分配：
//   - Idle (m01/m02/m05)   → 自动 idle 循环用，不映射
//   - Tap  (m07/m08)       → Step 3 触摸点击用，不映射
//   - Tap@Body (m09)       → 保留扩展点（语义"摸身体"），不映射
//   - Flick      (m03)     ← 本 map 用
//   - FlickDown  (m04)     ← 本 map 用
//   - FlickUp    (m06)     ← 本 map 用
//   - Flick@Body (m10)     ← 本 map 用
//
// Hiyori 的 Flick* 系列每个 group 只有 1 条 motion（index 0）。LLM 输出新词
// （map 没覆盖的"招手"/"叉腰"等）时 Live2DCanvas 降级 console.warn + no-op，
// 不报错；想加新动作只要在这里新增 key。
//
// v3-E2 换模型时整体重写本 map（新模型的 motion group 名字会变）。
// ---------------------------------------------------------------------------

export interface MotionEntry {
  group: string;  // Live2D motion group name（如 "Flick" / "FlickDown"）
  index: number;  // 该 group 内的 motion 索引（0-based）
}

export const motionMap: Record<string, MotionEntry> = {
  // 中文名 → Hiyori Flick* group。语义已通过 dev 调试钩子实测对齐 Hiyori
  // 的实际美术动作（见各 group 下注释）。Hiyori 没有"挥手 / 点头 / 鞠躬"等
  // 语义动作，因此本 map 也不收录这些词；LLM 若输出会被 useEffect 降级 warn。

  // Flick (m03)：放松状态下轻轻甩手 — 慵懒 / 随意
  '放松':       { group: 'Flick',       index: 0 },
  '随意':       { group: 'Flick',       index: 0 },
  '慵懒':       { group: 'Flick',       index: 0 },
  '没事':       { group: 'Flick',       index: 0 },

  // FlickDown (m04)：双手别在身后 — 害羞 / 收敛
  '害羞':       { group: 'FlickDown',   index: 0 },
  '不好意思':   { group: 'FlickDown',   index: 0 },
  '腼腆':       { group: 'FlickDown',   index: 0 },
  '小动作':     { group: 'FlickDown',   index: 0 },

  // FlickUp (m06)：小臂举起晃（像应援荧光棒）— 加油 / 兴奋
  '加油':       { group: 'FlickUp',     index: 0 },
  '兴奋':       { group: 'FlickUp',     index: 0 },
  '应援':       { group: 'FlickUp',     index: 0 },
  '欢呼':       { group: 'FlickUp',     index: 0 },
  '雀跃':       { group: 'FlickUp',     index: 0 },

  // Flick@Body (m10)：复合动作（Flick → FlickDown，带表情）— 撒娇 / 俏皮
  '撒娇':       { group: 'Flick@Body',  index: 0 },
  '俏皮':       { group: 'Flick@Body',  index: 0 },
  '调皮':       { group: 'Flick@Body',  index: 0 },
};

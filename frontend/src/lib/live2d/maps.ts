// v3-E2 chunk 5：从 character.{emotion,motion,hit_area}_map_json 解析出
// 当轮 Live2D 用的三个 map；JSON 字段为空 / parse 失败时回退到 v3-E1 的
// 全局默认（src/config/live2d.ts），保证 Hiyori 体验完全不变。
//
// 设计要点
// --------
// - parse 失败兜底 console.warn 而不是抛错，避免一行坏 JSON 让整个 Live2D
//   渲染失效。调试期试错友好。
// - DEFAULT_HIT_AREA_MAP 留空 ``{}``：v3-E1 没启用 hit-area 路由，先准备
//   契约；接通八重神子 8 个 HitAreas 时给那个角色写自己的 map。
// - v3-E2 chunk 7：``EmotionMap`` 从 ``Record<string, unknown>`` 升为
//   ``Record<string, string>``，value 直接是 Live2D expression 名（v3-E1
//   step5 占位 unknown 是因为没决定 binding 形状；本步定为最简单的"emotion
//   词 → expression 名"形态，跟 ``model.expression(name)`` 直接对接）。
//   未来若需要更复杂的 binding（参数偏移列表等）再升级类型 + ts strict 提
//   醒所有调用方调整。

import type { CharacterRow } from '../config';
import {
  emotionMap as DEFAULT_EMOTION_MAP,
  motionMap  as DEFAULT_MOTION_MAP,
  type MotionEntry,
} from '../../config/live2d';

export type EmotionMap = Record<string, string>;

export interface CharacterMaps {
  emotionMap: EmotionMap;
  motionMap:  Record<string, MotionEntry>;
  hitAreaMap: Record<string, string>;
}

const DEFAULT_HIT_AREA_MAP: Record<string, string> = {};

function parseOrDefault<T>(
  json: string | null | undefined,
  fallback: T,
  fieldName: string,
  characterId: number | undefined,
): T {
  if (json == null || json.trim() === '') return fallback;
  try {
    const parsed = JSON.parse(json) as unknown;
    if (parsed === null || typeof parsed !== 'object') {
      console.warn(
        `[live2d] character ${characterId ?? '?'}.${fieldName}` +
        ` parsed but not an object, falling back to default`,
      );
      return fallback;
    }
    return parsed as T;
  } catch (err) {
    console.warn(
      `[live2d] character ${characterId ?? '?'}.${fieldName} JSON parse failed,` +
      ` falling back to default:`, err,
    );
    return fallback;
  }
}

/**
 * 取出该 character 的 emotion / motion / hitArea map。
 *
 * - ``character`` 为 ``null`` / ``undefined`` → 全部走默认
 * - 单字段 NULL / 空 / parse 失败 → 该字段走默认（其他字段不受影响）
 *
 * @returns 永远返回完整三个 map，任何一个都不会是 null / undefined。
 */
export function resolveCharacterMaps(
  character: CharacterRow | null | undefined,
): CharacterMaps {
  if (!character) {
    return {
      emotionMap: DEFAULT_EMOTION_MAP,
      motionMap:  DEFAULT_MOTION_MAP,
      hitAreaMap: DEFAULT_HIT_AREA_MAP,
    };
  }
  return {
    emotionMap: parseOrDefault(
      character.emotion_map_json,
      DEFAULT_EMOTION_MAP,
      'emotion_map_json',
      character.id,
    ),
    motionMap: parseOrDefault(
      character.motion_map_json,
      DEFAULT_MOTION_MAP,
      'motion_map_json',
      character.id,
    ),
    hitAreaMap: parseOrDefault(
      character.hit_area_map_json,
      DEFAULT_HIT_AREA_MAP,
      'hit_area_map_json',
      character.id,
    ),
  };
}

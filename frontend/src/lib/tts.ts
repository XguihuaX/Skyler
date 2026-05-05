// v3-G' chunk 1b — frontend API client for /api/tts/voices.
//
// 同 lib/live2d.ts 的位置约定（v3-E2 commit 3b 决策：API helper 集中在
// lib/，等到 ≥ 5 个文件再考虑迁 src/api/）。

const BACKEND_BASE = 'http://127.0.0.1:8000';

// 与 backend/routes/tts_api.py 的 VoiceInfo / TtsProvider 对齐。
// 后端是 single source of truth；schema drift 时 build 立即报错。
//
// v3-G' patch：删除 ssml 字段。chunk 1a 把 ssml=true 当 "emotion 真生效"
// 标记是错的（DashScope SSML 没 emotion 属性，撤销）。emotion 控制全部走
// instruct 字段路径。未来 SSML rate/pitch/effect/bgm 真用上时再加回。
export interface VoiceInfo {
  id: string;
  label: string;
  instruct: boolean | null;   // null = SDK 文档没确认，true/false 是已确认
  traits: string;
}

export interface TtsProvider {
  id: string;
  label: string;
  voices: VoiceInfo[];
}

export interface TtsVoicesResponse {
  providers: TtsProvider[];
}

export async function fetchTtsVoices(): Promise<TtsVoicesResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/tts/voices`);
  if (!res.ok) throw new Error(`fetch tts voices failed: ${res.status}`);
  return (await res.json()) as TtsVoicesResponse;
}

// ---------------------------------------------------------------------------
// voice_model 字段格式工具：character.voice_model 存 JSON 字符串，向后兼容
// ---------------------------------------------------------------------------

// 后端 voice_config.parse_voice_config 解析的 JSON 形态：
//   {"provider": "cosyvoice", "voice": "longyumi_v3", "instruct_supported": false}
// 前端两级下拉编辑后写回这个 schema。
export interface VoiceModelJson {
  provider: string;
  voice: string;
  instruct_supported: boolean;
}

/**
 * 把 character.voice_model 字段（DB string）反向解析成 (provider, voice)。
 *
 * 三种 case：
 *   - 空 / null → 返回 null 让 UI 显示"未配置 / 全局默认"
 *   - 合法 JSON → 抽 provider / voice
 *   - 非 JSON 旧格式（v3-G' 前可能直接存 voice id）→ 返回 null 让 UI
 *     显示"自定义：原值"做向后兼容（用户保存时被转成新 schema）
 */
export function parseVoiceModelJson(
  raw: string | null | undefined,
): VoiceModelJson | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (
      parsed === null ||
      typeof parsed !== 'object' ||
      Array.isArray(parsed)
    ) {
      return null;
    }
    const obj = parsed as Record<string, unknown>;
    const provider = typeof obj.provider === 'string' ? obj.provider : '';
    const voice    = typeof obj.voice    === 'string' ? obj.voice    : '';
    if (!provider || !voice) return null;
    return {
      provider,
      voice,
      instruct_supported: Boolean(obj.instruct_supported),
    };
  } catch {
    return null;
  }
}

/**
 * 把 (provider, voice, instruct_supported) 序列化回 character.voice_model
 * 字段值。后端 ``parse_voice_config`` 直接消费此格式。
 */
export function buildVoiceModelJson(
  provider: string,
  voice: string,
  instructSupported: boolean,
): string {
  return JSON.stringify({
    provider,
    voice,
    instruct_supported: instructSupported,
  });
}

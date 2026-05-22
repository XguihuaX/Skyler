/**
 * v4 字幕剥离 client-side helper · mirror backend strip_ja_en_tags_for_subtitle。
 *
 * 背景(PM 真机暴露 2026-05-22):
 *   chat_history.content 入库时 backend `_update_memory` 5 道 strip(emotion /
 *   thinking / state_update / motion / tool_call)+ unknown-tag sanitize,
 *   **不剥** ``<ja>...</ja>`` / ``<en>...</en>`` 整段(白名单豁免 per
 *   _SUSPICIOUS_TAG_WHITELIST)+ **不剥** Fish ``[bracket]`` markers。
 *
 *   设计意图(per INV-9 §1.4.3 Option α):保 raw 让 LLM round-trip 学
 *   ja tag pattern(short_term restore 时 LLM 看到自己说过 raw 含 ja → 下
 *   turn 仍 follow);但 frontend ``fetchMessages`` 直接拿 raw 显示给用户
 *   导致 chat 框看到 ``"嗯，在。<ja>[composed]「うん、いるよ。」</ja>"``。
 *
 * 修法:frontend display layer client-side strip(此 module)。LLM context
 * 路径(short_term / chat_history fetch for restore)保 raw 不动;只在 UI
 * 渲染前调 ``stripJaEnTagsForSubtitle``。
 *
 * 镜像 backend regex(per backend/utils/text_filters.py):
 *   _JA_TAG_RE = re.compile(r"<ja>([\s\S]*?)</ja>", re.IGNORECASE)
 *   _EN_TAG_RE = re.compile(r"<en>([\s\S]*?)</en>", re.IGNORECASE)
 *   _FISH_EMOTION_MARKER_RE = re.compile(r"\[[^\[\]]+\]")
 */

const JA_TAG_RE = /<ja>[\s\S]*?<\/ja>/gi;
const EN_TAG_RE = /<en>[\s\S]*?<\/en>/gi;
// Fish [bracket] emotion markers · 不允许嵌套 inner []
const FISH_MARKER_RE = /\[[^\[\]]+\]/g;

/**
 * 字幕路径用 · 删 ``<ja>...</ja>`` / ``<en>...</en>`` 整段 + ``[bracket]``
 * markers,留中文裸文本给用户看。
 *
 * 空 / null / undefined → 原样返回。
 */
export function stripJaEnTagsForSubtitle(text: string | null | undefined): string {
  if (!text) return text ?? '';
  return text
    .replace(JA_TAG_RE, '')
    .replace(EN_TAG_RE, '')
    .replace(FISH_MARKER_RE, '');
}

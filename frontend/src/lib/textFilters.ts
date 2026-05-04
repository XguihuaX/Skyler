// v3-F 回归修（前端兜底）：渲染消息时剥 <thinking>...</thinking> 块。
//
// 后端 backend/utils/text_filters.py 已在写库前剥一道，理论上 chat_history
// 新行不会再带 thinking。但：
//   1. 老的 chat_history 行（修复部署前生成）仍含原始标签
//   2. WS streaming text_chunk 偶有边界把开标签先送达、闭标签后到的瞬间
// 为这两种情况兜底：消息气泡渲染时再正则扫一遍。
//
// JS regex 默认 `.` 不匹配换行，用 `[\\s\\S]` 等价 Python 的 re.DOTALL；
// 顺手吃掉块后紧贴的空白避免正文前空行。

const THINKING_BLOCK_RE = /<thinking>[\s\S]*?<\/thinking>\s*/gi;

export function stripThinking(text: string): string {
  if (!text) return text;
  return text.replace(THINKING_BLOCK_RE, '');
}

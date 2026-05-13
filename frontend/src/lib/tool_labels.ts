// UX-004 — tool_name 前缀 → 用户友好 loading label 映射
//
// LLM 偶尔不遵守 prompt 中的"先输出过渡语"约束直接 silent 调 tool,
// frontend 凭 WS event ``tool_use_start`` 的 tool_name 给一行 loading 文本
// 兜底。前缀语义对齐 backend _extractProvider(``capability_panel.tsx``)。
//
// 设计:**前缀 mapping** 而非走 API 动态查 — backend capability category
// 已经稳定按 dot 前缀分组,UI label 没必要联 backend round-trip。新增
// capability 只在本表加一条(或落 fallback "查询中…"自然 OK)。

interface ToolLabelEntry {
  /** tool_name 前缀(到第一个 ``.`` 之前)。``ext.X`` 走单独 startsWith */
  prefix: string;
  /** 显示文案,文字简短(< 12 字),自然短句 */
  label: string;
}

// 顺序敏感:第一个 startsWith 匹配胜出。``ext.`` 类前缀放最前
const TOOL_LABEL_TABLE: ToolLabelEntry[] = [
  // chunk 14 — activity timeline
  { prefix: 'activity.', label: '查今天的活动…' },
  // calendar(apple_calendar / google_calendar / calendar router)
  { prefix: 'apple_calendar.', label: '查日历…' },
  { prefix: 'google_calendar.', label: '查日历…' },
  { prefix: 'calendar.', label: '查日历…' },
  // chunk 14 activity also includes time anchor — fallback 兜底
  { prefix: 'time.', label: '看看时间…' },
  // music(UX-005:netease 全归 music,含 API + local 共 13 caps)
  { prefix: 'netease.', label: '查歌单…' },
  // bilibili
  { prefix: 'bilibili.', label: '看视频信息…' },
  // media_control(系统级播放控制)
  { prefix: 'media.', label: '控制播放…' },
  // social (UX-005 新建,目前 xhs 1 cap)
  { prefix: 'xhs.', label: '解析小红书…' },
  // screen(chunk 8a)
  { prefix: 'screen.', label: '看屏幕…' },
  // character state
  { prefix: 'character.', label: '更新状态…' },
  // clipboard
  { prefix: 'clipboard.', label: '看剪贴板…' },
  // files (docx)
  { prefix: 'docx.', label: '读文档…' },
  // memory(save_memory / get_recent / search_memory)
  { prefix: 'save_memory', label: '记一下…' },
  { prefix: 'search_memory', label: '回忆一下…' },
  { prefix: 'get_recent_memory', label: '回忆一下…' },
  // MCP external — ext.X.Y(filesystem / brave-search / notion / etc)
  { prefix: 'ext.filesystem', label: '看本地文件…' },
  { prefix: 'ext.brave-search', label: '搜网页…' },
  { prefix: 'ext.notion', label: '查 Notion…' },
];

const FALLBACK_LABEL = '查询中…';

export function toolLoadingLabel(toolName: string | null | undefined): string {
  if (!toolName) return FALLBACK_LABEL;
  for (const entry of TOOL_LABEL_TABLE) {
    if (toolName.startsWith(entry.prefix)) return entry.label;
  }
  return FALLBACK_LABEL;
}

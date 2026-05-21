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
//
// 2026-05-21 INV-7 §1.7 retro-fix:P1.media / P1.apple_calendar / P1.bilibili
// fold 后 cap name 是单字 namespace(`media` / `apple_calendar` / `bilibili`),
// 失去 `.` 后缀。下面 3 处 prefix 去末尾 `.` 兼容单字 + 多字:
//   `'media'.startsWith('media')` = true(fold 后单字)
//   `'media.next_track'.startsWith('media')` = true(假设 fold 前/未来多字仍兼容)
// **改后需 frontend yarn build 才在生产 UI 生效**(本 commit 不触发 build)。
// 详 INV-7 §1.3 特异 c · option A。
const TOOL_LABEL_TABLE: ToolLabelEntry[] = [
  // chunk 14 — activity timeline
  { prefix: 'activity.', label: '查今天的活动…' },
  // calendar(apple_calendar fold 单字 + google_calendar / calendar router)
  { prefix: 'apple_calendar', label: '查日历…' },  // INV-7 §1.7 retro-fix (P1.apple_calendar fold)
  { prefix: 'google_calendar.', label: '查日历…' },
  { prefix: 'calendar.', label: '查日历…' },
  // chunk 14 activity also includes time anchor — fallback 兜底
  { prefix: 'time.', label: '看看时间…' },
  // music(UX-005:netease 全归 music;INV-7 §2 P1.netease fold 后拆双 dispatcher
  // netease_web + netease_local;retro-fix 去末尾 . 同 P1.bilibili 模式)
  { prefix: 'netease_web', label: '查歌单…' },     // INV-7 §2 P1.netease fold (web)
  { prefix: 'netease_local', label: '本地播放…' },  // INV-7 §2 P1.netease fold (local)
  // bilibili (INV-7 §1.7 P1.bilibili fold 单字)
  { prefix: 'bilibili', label: '看视频信息…' },  // INV-7 §1.7 retro-fix (P1.bilibili fold)
  // media_control(系统级播放控制;INV-6 §2 P1.media fold 单字)
  { prefix: 'media', label: '控制播放…' },  // INV-7 §1.7 retro-fix (P1.media fold)
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

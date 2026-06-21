// 聊天气泡时间小字 · 输出系统本地时区(toLocaleTimeString 默认本地)。
//
// 兼容两种入参:
//   · 后端 chat_history.created_at(naive UTC,"2026-06-21 11:30:00",无 Z)
//   · WS 客户端创建(new Date().toISOString(),带 Z)
//
// 解析关键(照 lib/activity_timeline.ts:96-98 同款):
//   · replace ' '→'T':Safari / 老 V8 解析空格分隔 datetime 字串返 NaN
//   · 无 Z 补 Z:naive 字串若不显式标 UTC,JS Date 按本地解读 → 偏 8h
//
// 输出:
//   · 今天 → "HH:MM"
//   · 昨天 → "昨天 HH:MM"
//   · 更早 → "M月D日 HH:MM"
// 入参非法 / 空 → 返 "",caller(Bubble)负责"空就不显"。

export function formatBubbleTime(raw: string | undefined | null): string {
  if (!raw) return '';
  const iso = raw.replace(' ', 'T') + (raw.endsWith('Z') ? '' : 'Z');
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';

  const now = new Date();
  const hhmm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

  // 按本地日期比较(toDateString 去时分秒 + 走本地 tz)
  const dDay = d.toDateString();
  const todayDay = now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const yesterdayDay = yesterday.toDateString();

  if (dDay === todayDay) return hhmm;
  if (dDay === yesterdayDay) return `昨天 ${hhmm}`;
  return `${d.getMonth() + 1}月${d.getDate()}日 ${hhmm}`;
}

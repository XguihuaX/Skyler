import { memo, useEffect, useRef } from 'react';
import { useAppStore, type ChatMessage } from '../store';
import { stripThinking } from '../lib/textFilters';

// v3-G chunk 2 / 2.6 / 4: proactive trigger.name -> 灰字前缀 label。
// 加新 trigger 时在这里 append 即可。映射不到 → 通用兜底 "✨（主动陪伴）"。
const PROACTIVE_PREFIX: Record<string, string> = {
  morning_briefing: '🌅（早安简报）',
  wake_call: '🌅（叫早）',
  lunch_call: '🍱（午饭呼叫）',
  dinner_call: '🍽（晚饭呼叫）',
  bedtime_chat: '🌙（睡前）',
  long_idle: '💭（轻触你）',
};

const Bubble = memo(function Bubble({ m }: { m: ChatMessage }) {
  const isUser = m.role === 'user';

  // v3-E1 Step Z.2：'touch' 行 user-side 显示成"（碰了一下）"灰字而不是
  // 裸字符串 [touch]，让对话历史看起来像 Momo 自然回应了一下抚摸；
  // assistant 行正常显示。'proactive' 没有 user 行（engine 不写 user 占位），
  // 所以 user-side 不会命中 proactive 分支；assistant 侧加灰字前缀。
  if (isUser && m.kind === 'touch') {
    return (
      <div className="flex justify-end">
        <span
          className="text-xs italic"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          （碰了一下）
        </span>
      </div>
    );
  }

  // v3-F 回归修：渲染前剥 <thinking>...</thinking>。后端写库前已剥一道，
  // 此处兜底处理老历史数据 + streaming 边界
  const displayContent = stripThinking(m.content);

  // v3-G chunk 2: proactive assistant 气泡 = 灰字前缀 + 正常气泡正文。
  // 前缀放在气泡上方，UI 与 emotion / motion 标签层一致地"轻"，不抢视觉。
  const proactivePrefix =
    !isUser && m.kind === 'proactive'
      ? PROACTIVE_PREFIX[m.proactiveTrigger ?? ''] ?? '✨（主动陪伴）'
      : null;

  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
      {proactivePrefix && (
        <span
          className="text-xs italic mb-1 px-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {proactivePrefix}
        </span>
      )}
      <div
        className="max-w-[78%] rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap break-words shadow"
        style={
          isUser
            ? {
                background: 'var(--color-bubble-user)',
                color: 'var(--color-bubble-user-text)',
              }
            : {
                background: 'var(--color-bubble-ai)',
                color: 'var(--color-bubble-ai-text)',
                border: '1px solid var(--color-border-subtle)',
              }
        }
      >
        {displayContent}
        {m.streaming && (
          <span
            className="inline-block w-1.5 h-3 ml-1 align-baseline animate-pulse"
            style={{ background: 'var(--color-text-secondary)' }}
          />
        )}
      </div>
    </div>
  );
});

export default function ChatHistory() {
  const messages = useAppStore((s) => s.chatMessages);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom when messages change.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto px-6 py-4 space-y-3"
    >
      {messages.length === 0 ? (
        <div
          className="h-full flex items-center justify-center text-sm"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          开始一段对话吧
        </div>
      ) : (
        messages.map((m) => <Bubble key={m.id} m={m} />)
      )}
    </div>
  );
}

import { useMemo } from 'react';
import { useAppStore, type ChatMessage } from '../store';

/**
 * Floating Galgame-style bubble overlaid on the CharacterView background.
 * 仅渲染 store.chatMessages 中最新一条 assistant 消息。
 */
export default function CharacterDialogueBubble() {
  const messages = useAppStore((s) => s.chatMessages);

  const last: ChatMessage | null = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i];
    }
    return null;
  }, [messages]);

  if (!last) return null;

  return (
    <div
      className="absolute bottom-24 left-0 right-0 mx-auto z-20 max-w-[60%] min-w-[200px] w-fit
                 backdrop-blur-md rounded-2xl px-5 py-3
                 shadow-lg text-base whitespace-pre-wrap break-words
                 transition-opacity duration-200"
      style={{
        background: 'color-mix(in srgb, var(--color-bubble-ai) 80%, transparent)',
        color: 'var(--color-bubble-ai-text)',
        boxShadow: '0 10px 25px -5px color-mix(in srgb, var(--color-bg-base) 60%, transparent)',
      }}
    >
      {last.content}
      {last.streaming && (
        <span className="inline-flex gap-0.5 ml-1 align-middle">
          <span
            className="w-1 h-1 rounded-full animate-bounce [animation-delay:0ms]"
            style={{ background: 'var(--color-bubble-ai-text)' }}
          />
          <span
            className="w-1 h-1 rounded-full animate-bounce [animation-delay:150ms]"
            style={{ background: 'var(--color-bubble-ai-text)' }}
          />
          <span
            className="w-1 h-1 rounded-full animate-bounce [animation-delay:300ms]"
            style={{ background: 'var(--color-bubble-ai-text)' }}
          />
        </span>
      )}
    </div>
  );
}

import { useEffect, useMemo, useState } from 'react';
import { useAppStore, type ChatMessage } from '../store';
import { stripThinking } from '../lib/textFilters';
import { fadeForAge } from '../lib/fadeCurve';

/**
 * Floating Galgame-style bubble overlaid on the CharacterView background.
 * 仅渲染 store.chatMessages 中最新一条 assistant 消息。
 *
 * UX-007: 按 message age 渐进淡化(60s 内 100% 焦点期 → 5min+ 固定 25%),
 * 不让旧消息长时间挡 Live2D 视觉。曲线见 ``lib/fadeCurve.ts``。规则:
 *   * status === 'speaking'(TTS 正在播)→ 维持 100%,因为该消息就是当前正在播的那条
 *   * 鼠标 hover 临时 100%,移开重回淡化值
 *   * streaming 中消息也维持 100%(age 极小落入阶段 1)
 */
export default function CharacterDialogueBubble() {
  const messages = useAppStore((s) => s.chatMessages);
  const status = useAppStore((s) => s.status);

  const last: ChatMessage | null = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i];
    }
    return null;
  }, [messages]);

  // 每 5s tick 一下让 fade 重算 — 5s 颗粒度对视觉够,频率低对性能友好
  const [, setNowTick] = useState(0);
  useEffect(() => {
    if (!last) return;
    const id = window.setInterval(() => setNowTick((n) => n + 1), 5000);
    return () => window.clearInterval(id);
  }, [last]);

  const [hovered, setHovered] = useState(false);

  if (!last) return null;

  // v3-F 回归修:渲染前剥 <thinking>...</thinking>。后端写库前已剥一道,
  // 此处兜底处理老历史数据 + streaming 边界
  const displayContent = stripThinking(last.content);

  // UX-007: 按 age 算淡化。ts 是 performance.now()-based(单调时钟),与
  // performance.now() 配对计算 ageMs 精度足够。
  const ageMs = Math.max(0, performance.now() - last.ts);
  const fade = fadeForAge(ageMs);

  // 三道例外覆盖到 100%:
  //   * TTS 正在播 (status='speaking') — 该消息就是当前播放的(TTS full-utterance)
  //   * hover 上去临时恢复
  //   * streaming 中 (age 极小落入阶段 1) — fadeForAge 自然返 {1,1}
  const isCurrentlySpeaking = status === 'speaking';
  const effectiveOpacity = hovered || isCurrentlySpeaking ? 1 : fade.opacity;
  const effectiveScale = hovered || isCurrentlySpeaking ? 1 : fade.scale;

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="absolute bottom-24 left-0 right-0 mx-auto z-20 max-w-[60%] min-w-[200px] w-fit
                 backdrop-blur-md rounded-2xl px-5 py-3
                 shadow-lg text-base whitespace-pre-wrap break-words
                 transition-opacity duration-200 transition-transform"
      style={{
        background: 'color-mix(in srgb, var(--color-bubble-ai) 80%, transparent)',
        color: 'var(--color-bubble-ai-text)',
        boxShadow: '0 10px 25px -5px color-mix(in srgb, var(--color-bg-base) 60%, transparent)',
        opacity: effectiveOpacity,
        transform: `scale(${effectiveScale})`,
        transformOrigin: 'bottom center',
        transitionDuration: '300ms',
      }}
    >
      {displayContent}
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

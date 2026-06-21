/**
 * CharacterSpeechBubble · 大/小窗共用「她最新那句」浮台词气泡。
 *
 * 历史:大窗 ``CharacterDialogueBubble`` 与小窗 ``WidgetSpeechBubble`` 两个
 * 独立组件,各自因不同理由被删(audit_chat_panel 方案 1 / 06-06 小窗极简)。
 * 本组件统一替代两者,挂两窗,共一份取数 + 生命周期逻辑。
 *
 * 取数(报告 §4 标准用法):
 *   · 订阅 ``streamingMessageId`` + ``chatMessages``
 *   · streaming 期间:activeId = streamingId, content 随 chunk 实时累加
 *   · finalize 后(streamingId → null):activeId 保留 → 进入 linger 倒计时
 *   · 下一句 streaming 开始:清旧 timer,activeId 切到新 id,立即切换
 *   · 首次 mount(从未 stream 过)→ activeId=null → 不显(不自动复活老消息)
 *
 * 显示策略:
 *   · 仅 assistant + kind ∈ ('normal' | 'proactive') · touch / user 跳过
 *   · proactive 复用 ChatHistory.tsx 的 PROACTIVE_PREFIX 灰字前缀
 *     (PM 拒改 ChatHistory.tsx 加 export, 这里复制一份;后续可抽
 *      lib/proactive_labels.ts 统一)
 *   · 文本 stripThinking 兜底(后端已剥, streaming 边界二次保险)
 *   · streaming 中尾巴加脉冲光标(同 ChatHistory)
 *
 * 生命周期:
 *   · streaming → 常显
 *   · finalize → linger:widget 8s · panel 2.5s · 下一句立即切
 *   · 切角色/对话/cancel(streamingId→null + removeChatMessage)→ msg 找不到 → 优雅 fade
 *
 * 位置(避开两窗既有浮件):
 *   · widget:top:48 left:12 right:12 横铺 · 让出左上 StatusBadge(top:3 left:3,
 *     ~24h)+ 右上 CharacterStatePanel widget 态(top:12 right:12,~24h)
 *   · panel:top:24 left:24 right:24 横铺 · 内层 maxWidth:420 mx-auto
 *     避开 CharacterStatePanel(在 Panel 根容器外, 不冲突)与 ChatHistoryPanel
 *     (右上, 居中 + maxWidth 让 SpeechBubble 不与之打架)
 *
 * z-index / 交互:
 *   · z-30 压顶 · pointer-events:none(纯信息浮件, 不挡 Live2D 点击)
 *
 * 动画:framer-motion(已装 12.38)AnimatePresence + opacity/y fade
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useAppStore, type ChatMessage } from '../../store';
import { stripThinking } from '../../lib/textFilters';

// 复制自 ChatHistory.tsx:7-14(同步更新; 后续抽 lib/proactive_labels.ts)
const PROACTIVE_PREFIX: Record<string, string> = {
  morning_briefing: '🌅（早安简报）',
  wake_call: '🌅（叫早）',
  lunch_call: '🍱（午饭呼叫）',
  dinner_call: '🍽（晚饭呼叫）',
  bedtime_chat: '🌙（睡前）',
  long_idle: '💭（轻触你）',
};

const LINGER_MS: Record<'widget' | 'panel', number> = {
  widget: 8000,  // 小窗无历史 · 让用户随时回头看
  panel: 2500,   // 大窗 ChatHistory 已收 · 短显避免与历史重复抢视觉
};

interface Props {
  mode: 'widget' | 'panel';
}

export default function CharacterSpeechBubble({ mode }: Props) {
  const streamingId = useAppStore((s) => s.streamingMessageId);
  const messages = useAppStore((s) => s.chatMessages);

  const [activeId, setActiveId] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<number | null>(null);

  // 流式启动 / finalize 转换核心 effect。
  // deps 不含 activeId/messages — 防止 chunk 抖动重设 linger timer。
  useEffect(() => {
    if (streamingId) {
      // 新句来了 / 流中 → 清旧 linger, 锁定 activeId, 常显
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      setActiveId(streamingId);
      setVisible(true);
      return;
    }
    // streamingId === null(刚 finalize 或 cancel 或从未流)
    if (activeId === null) return;  // 从未流, 什么都不显
    // 进入 linger
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    const ms = LINGER_MS[mode];
    timerRef.current = window.setTimeout(() => {
      setVisible(false);
      timerRef.current = null;
    }, ms);
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamingId, mode]);

  // 实时取要渲染的 message · streaming 中 content chunk 累加 → 自动 re-render
  const msg = useMemo<ChatMessage | null>(() => {
    if (!visible || !activeId) return null;
    const m = messages.find((x) => x.id === activeId);
    if (!m) return null;  // 切角色/对话/cancel · 旧 id 不存在 → 优雅 fade
    if (m.role !== 'assistant') return null;
    if (m.kind !== 'normal' && m.kind !== 'proactive') return null;
    return m;
  }, [visible, activeId, messages]);

  // PM 2026-06-21 微调(仅 widget 分支):
  //   · 垂直 50% 真居中(translateY(-50%) 由外层 wrapper 设 · 不与 framer
  //     motion 的 y 动画 transform 打架)
  //   · 文字 opacity 抬回 1.0(原 0.85 整体 motion 太透读不清)
  //   · 背景单独透一档(color-mix 75% · blur 8 背景模糊保留)
  // panel 分支 wrapperStyle / bg 全保原样(虽然 Panel.tsx 当前未挂载本组件,
  // 代码留 valid 备后续复活)。
  const wrapperStyle: React.CSSProperties = mode === 'widget'
    ? { top: '50%', left: 12, right: 12, transform: 'translateY(-50%)' }
    : { top: '60%', left: 24, right: 24 };

  const innerMaxWidth = mode === 'widget' ? '100%' : 420;

  // widget 单独透背景 · panel 保持 var token 不透
  const bubbleBackground = mode === 'widget'
    ? 'color-mix(in srgb, var(--color-bubble-ai) 75%, transparent)'
    : 'var(--color-bubble-ai)';

  return (
    // 外层定位 wrapper:absolute + top + translateY(-50%) 真居中,
    // 不进 framer 动画路径 · 避开 motion y/transform 覆盖问题。
    // AnimatePresence 在内层管 motion.div mount/unmount fade。
    <div
      className="absolute z-30 pointer-events-none flex flex-col items-center"
      style={wrapperStyle}
    >
      <AnimatePresence>
        {msg && (
          <motion.div
            key="char-speech-bubble"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="flex flex-col items-center"
          >
            {msg.kind === 'proactive' && (
              <div
                className="text-[11px] italic mb-1 px-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {PROACTIVE_PREFIX[msg.proactiveTrigger ?? ''] ?? '✨（主动陪伴）'}
              </div>
            )}
            <div
              className="rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap break-words shadow-lg"
              style={{
                background: bubbleBackground,
                color: 'var(--color-bubble-ai-text)',
                border: '1px solid var(--color-border-subtle)',
                maxWidth: innerMaxWidth,
                backdropFilter: 'blur(8px)',
                WebkitBackdropFilter: 'blur(8px)',
              }}
            >
              {stripThinking(msg.content)}
              {msg.streaming && (
                <span
                  className="inline-block w-1.5 h-3 ml-1 align-baseline animate-pulse"
                  style={{ background: 'var(--color-text-secondary)' }}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

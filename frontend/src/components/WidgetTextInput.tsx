/**
 * 2026-06-05 · 小窗文字输入条。
 *
 * 只在 Widget.tsx 内 inputMode==='text' 时渲染(条件渲染由 Widget.tsx 处理,
 * 不在本组件内 gate · 让组件本身可独立测试 / 复用)。
 *
 * 行为:
 *   - 受控单行 input · Enter(不带 shift)发送 · 空 trim 不发
 *   - sendText 走 useAppApi(同大窗 ChatInput.tsx:34 的链路;后端 useWebSocket
 *     `sendText` callback,见 hooks/useWebSocket.ts:540)
 *   - 发送成功后清空
 *   - autoFocus:用户刚切到 text 态期望立即能输入
 *
 * 视觉:吃 themes.css 的 `--glass-*` token 跟 Round 3/4/5 大窗浮件视觉统一,
 * 不造 v3 老样式(小窗其它 v3 件视觉迁移留给后续批)。
 */
import { useState } from 'react';
import { useAppApi } from '../contexts/appApi';

export default function WidgetTextInput() {
  const [text, setText] = useState('');
  const { sendText } = useAppApi();

  const send = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    sendText(trimmed);
    setText('');
  };

  return (
    <input
      type="text"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          send();
        }
      }}
      placeholder="和她说点什么…"
      className="w-full text-sm outline-none"
      style={{
        borderRadius: 'var(--glass-radius)',
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
        border: 'var(--glass-border)',
        boxShadow: 'var(--glass-shadow)',
        color: 'var(--glass-text)',
        textShadow: 'var(--glass-text-shadow)',
        padding: '8px 14px',
      }}
      autoFocus
      autoComplete="off"
      spellCheck={false}
    />
  );
}

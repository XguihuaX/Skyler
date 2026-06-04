// 共享 card 外壳 · 用 glass-* token 跟主聊天浮件视觉一致。
import { type ReactNode } from 'react';

interface CardProps {
  title: ReactNode;
  rightSlot?: ReactNode;
  children: ReactNode;
}

export default function Card({ title, rightSlot, children }: CardProps) {
  return (
    <section
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
        border: 'var(--glass-border)',
        boxShadow: 'var(--glass-shadow)',
        borderRadius: 'var(--glass-radius)',
        color: 'var(--glass-text)',
        textShadow: 'var(--glass-text-shadow)',
      }}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">{title}</h3>
        {rightSlot && <div className="text-[11px]">{rightSlot}</div>}
      </div>
      {children}
    </section>
  );
}

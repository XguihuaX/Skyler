import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../store';

export default function NotificationToast() {
  const notifications = useAppStore((s) => s.notifications);
  const [visibleId, setVisibleId] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const last = notifications.length > 0 ? notifications[notifications.length - 1] : null;

  useEffect(() => {
    if (!last) return;
    setVisibleId(last.id);
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      setVisibleId(null);
      timerRef.current = null;
    }, 4000);
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [last?.id]);

  const notification = notifications.find((n) => n.id === visibleId);
  if (!notification) return null;

  // alarm / notify 共享主题色，靠 dot 颜色区分类型（保留语义色）
  const accentDot = notification.type === 'alarm' ? '#F59E0B' : '#06B6D4';

  return (
    <div
      className="absolute top-3 right-3 z-50 backdrop-blur-md text-sm rounded-lg px-4 py-2 shadow-lg max-w-xs flex items-center gap-2"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-elevated) 85%, transparent)',
        color: 'var(--color-text-primary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: accentDot }}
      />
      <span className="flex-1">{notification.content}</span>
    </div>
  );
}

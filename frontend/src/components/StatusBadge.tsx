import { AiStatus } from '../store';

interface StatusBadgeProps {
  status: AiStatus;
}

// 状态色：listening 绑定主题 accent；其他保留语义色（thinking/speaking/interrupted
// 各承担独立含义，跨主题保持可识别）。
type StatusVisual = {
  label: string;
  bg: string;
  text: string;
  dot: string;
};

const statusConfig: Record<AiStatus, StatusVisual> = {
  idle: {
    label: '空闲',
    bg: 'color-mix(in srgb, var(--color-bg-elevated) 60%, transparent)',
    text: 'var(--color-text-primary)',
    dot: 'var(--color-text-secondary)',
  },
  listening: {
    label: '聆听中',
    bg: 'color-mix(in srgb, var(--color-accent) 70%, transparent)',
    text: 'var(--color-bubble-user-text)',
    dot: 'var(--color-text-accent)',
  },
  thinking: {
    label: '思考中',
    bg: 'rgba(245, 158, 11, 0.7)',
    text: '#FFFFFF',
    dot: '#FCD34D',
  },
  speaking: {
    label: '说话中',
    bg: 'rgba(16, 185, 129, 0.7)',
    text: '#FFFFFF',
    dot: '#6EE7B7',
  },
  interrupted: {
    label: '已打断',
    bg: 'rgba(244, 63, 94, 0.7)',
    text: '#FFFFFF',
    dot: '#FDA4AF',
  },
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const { label, bg, text, dot } = statusConfig[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium backdrop-blur-sm transition-colors duration-300"
      style={{ background: bg, color: text }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: dot }}
      />
      {label}
    </span>
  );
}

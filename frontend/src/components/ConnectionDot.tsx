import { Circle } from 'lucide-react';
import { useAppStore, ConnectionStatus } from '../store';

const colorMap: Record<ConnectionStatus, { color: string; pulse: boolean }> = {
  disconnected: { color: '#F43F5E', pulse: false },  // rose-500
  connecting:   { color: '#FBBF24', pulse: true },   // amber-400
  connected:    { color: '#10B981', pulse: false },  // emerald-500
};

export default function ConnectionDot() {
  const connection = useAppStore((s) => s.connection);
  const { color, pulse } = colorMap[connection];
  return (
    <Circle
      size={12}
      fill="currentColor"
      strokeWidth={0}
      className={`transition-colors duration-300 ${pulse ? 'animate-pulse' : ''}`}
      style={{ color }}
    />
  );
}

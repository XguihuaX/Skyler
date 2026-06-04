import { useEffect, useState } from 'react';
import { useAppStore } from '../../../store';
import { fetchHealth, type HealthResponse } from '../../../lib/config';
import Card from './Card';

function connDotColor(c: 'disconnected' | 'connecting' | 'connected'): string {
  if (c === 'connected') return 'rgb(34, 197, 94)';
  if (c === 'connecting') return 'rgb(245, 158, 11)';
  return 'rgb(239, 68, 68)';
}

function aiStatusColor(s: string): string {
  if (s === 'idle') return 'var(--color-text-secondary)';
  if (s === 'listening') return 'rgb(34, 197, 94)';
  if (s === 'thinking') return 'rgb(245, 158, 11)';
  if (s === 'speaking') return 'var(--color-accent)';
  if (s === 'interrupted') return 'rgb(239, 68, 68)';
  return 'var(--color-text-secondary)';
}

function modelStateBadge(state: string | undefined): { label: string; color: string } {
  if (state === 'ready') return { label: 'ready', color: 'rgb(34, 197, 94)' };
  if (state === 'loading') return { label: 'loading', color: 'rgb(245, 158, 11)' };
  return { label: state ?? '?', color: 'var(--color-text-secondary)' };
}

export default function ConnectionCard() {
  const connection = useAppStore((s) => s.connection);
  const status     = useAppStore((s) => s.status);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetchHealth();
        if (!cancelled) { setHealth(r); setHealthErr(null); }
      } catch (e) {
        if (!cancelled) setHealthErr((e as Error).message);
      }
    };
    void tick();
    const h = setInterval(tick, 5000);
    return () => { cancelled = true; clearInterval(h); };
  }, []);

  const emb = modelStateBadge(health?.models?.embedding);
  const wh  = modelStateBadge(health?.models?.whisper);
  const llm = modelStateBadge(health?.models?.llm);

  return (
    <Card title="🔌 连接 / 后端">
      <div className="space-y-3 text-xs">
        {/* WS */}
        <div className="flex items-center justify-between">
          <span style={{ color: 'var(--color-text-secondary)' }}>WebSocket</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full"
              style={{ background: connDotColor(connection) }} />
            <span style={{ color: 'var(--color-text-primary)' }}>{connection}</span>
          </span>
        </div>

        {/* AI status */}
        <div className="flex items-center justify-between">
          <span style={{ color: 'var(--color-text-secondary)' }}>AI 状态</span>
          <span style={{ color: aiStatusColor(status) }}>{status}</span>
        </div>

        {/* /api/health */}
        <div
          className="pt-2 mt-1 space-y-1.5"
          style={{ borderTop: '1px dashed var(--color-border-subtle)' }}
        >
          <div className="flex items-center justify-between">
            <span style={{ color: 'var(--color-text-secondary)' }}>warm-up</span>
            {healthErr ? (
              <span style={{ color: 'rgb(239, 68, 68)' }}>fetch 失败</span>
            ) : (
              <span style={{ color: 'var(--color-text-primary)' }}>
                {health?.status ?? '…'}
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            <div>
              <div style={{ color: 'var(--color-text-secondary)' }}>embedding</div>
              <div style={{ color: emb.color }}>{emb.label}</div>
            </div>
            <div>
              <div style={{ color: 'var(--color-text-secondary)' }}>whisper</div>
              <div style={{ color: wh.color }}>{wh.label}</div>
            </div>
            <div>
              <div style={{ color: 'var(--color-text-secondary)' }}>llm</div>
              <div style={{ color: llm.color }}>{llm.label}</div>
            </div>
          </div>
          <p className="text-[10px]" style={{ color: 'var(--color-text-secondary)', opacity: 0.7 }}>
            poll /api/health 每 5s · llm 标 ready 是 LiteLLM lazy(首次调用才连)。
          </p>
        </div>
      </div>
    </Card>
  );
}

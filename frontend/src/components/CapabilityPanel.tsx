// v3-G chunk 0 — Momo 能做什么 / Capability 总览面板。
//
// 由 SettingsPanel 作为一个 Section 挂入（README "tab" 用语已在报告里
// 注明 deviation）。卡片按 category 分组显示，每张卡含 icon、健康状态点、
// consumer / trigger badge 和单卡刷新按钮。
//
// 风格基线：与 CharacterPanel 同款 —— 圆角 lg、`var(--color-bg-surface)` 60%
// 透明度做卡片底色、`var(--color-text-secondary)` 做弱化色（themes.css
// 不存在 muted / error 变量，已在 v3-G' patch (d) 踩过坑，沿用 secondary）。

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Calendar,
  Circle,
  Clock,
  Cloud,
  Image as ImageIcon,
  Music,
  RefreshCw,
  Tv,
  Wand2,
  Webhook,
  type LucideIcon,
} from 'lucide-react';
import {
  fetchCapabilities,
  runHealthCheck,
  type CapabilityDTO,
  type CapabilityHealth,
} from '../lib/capabilities';

// ---------------------------------------------------------------------------
// icon 映射：capability.icon 字符串 → lucide-react 组件。未知 fallback 圆点。
// 后续加新 capability 时按需扩。保持小集合避免 bundle 膨胀。
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, LucideIcon> = {
  clock: Clock,
  calendar: Calendar,
  music: Music,
  tv: Tv,
  cloud: Cloud,
  webhook: Webhook,
  wand: Wand2,
  image: ImageIcon,
  circle: Circle,
};

function CapabilityIcon({ name }: { name: string }) {
  const Icon = ICON_MAP[name] ?? Circle;
  return <Icon size={18} />;
}

// ---------------------------------------------------------------------------
// 健康状态点 — 绿/黄/红/灰
// ---------------------------------------------------------------------------

const HEALTH_LABEL: Record<CapabilityHealth['status'], string> = {
  healthy: '健康',
  warn: '注意',
  error: '异常',
  unknown: '未检查',
};

function HealthDot({ status }: { status: CapabilityHealth['status'] }) {
  // var(--color-accent) 作为 healthy 的色（每个主题里都是品牌强调色，绿系/
  // 蓝系/紫系不一，但是"正向状态"的语义统一）；warn / error / unknown 用
  // 内联色（themes.css 没有 success/warn/error 变量，DESIGN.md L1045 记录）。
  const color =
    status === 'healthy'
      ? 'var(--color-accent)'
      : status === 'warn'
        ? '#d97706' // amber-600，与主题中性
        : status === 'error'
          ? '#dc2626' // red-600
          : 'var(--color-text-secondary)';
  return (
    <span
      className="inline-block w-2 h-2 rounded-full shrink-0"
      style={{ background: color }}
      aria-label={HEALTH_LABEL[status]}
      title={HEALTH_LABEL[status]}
    />
  );
}

// ---------------------------------------------------------------------------
// badge — consumers / trigger_modes
// ---------------------------------------------------------------------------

const CONSUMER_LABEL: Record<string, string> = {
  chat_agent: 'ChatAgent',
  scheduler: 'Scheduler',
  webhook: 'Webhook',
};

const TRIGGER_LABEL: Record<string, string> = {
  on_demand: '按需',
  scheduled: '定时',
  event_driven: '事件',
};

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded"
      style={{
        background: 'var(--color-bg-elevated)',
        color: 'var(--color-text-secondary)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// 单张卡
// ---------------------------------------------------------------------------

interface CardProps {
  cap: CapabilityDTO;
  onRefresh: (name: string) => Promise<void>;
}

function CapabilityCard({ cap, onRefresh }: CardProps) {
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefresh(cap.name);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div
      className="rounded-lg p-3"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <div className="flex items-start gap-3">
        <span
          className="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
          style={{
            background: 'var(--color-bg-elevated)',
            color: 'var(--color-text-primary)',
          }}
        >
          <CapabilityIcon name={cap.icon} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="text-sm font-medium truncate"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {cap.display_name}
            </span>
            <span className="flex items-center gap-1 ml-auto shrink-0">
              <HealthDot status={cap.health.status} />
              <span
                className="text-[10px]"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {HEALTH_LABEL[cap.health.status]}
              </span>
            </span>
          </div>
          <p
            className="text-[11px] mt-0.5"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {cap.category} · {cap.name}
          </p>
          <p
            className="text-xs mt-2"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {cap.description}
          </p>

          <div className="flex flex-wrap items-center gap-1 mt-2">
            <span
              className="text-[10px]"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              谁能调：
            </span>
            {cap.consumers.map((c) => (
              <Badge key={c}>{CONSUMER_LABEL[c] ?? c}</Badge>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1 mt-1">
            <span
              className="text-[10px]"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              触发：
            </span>
            {cap.trigger_modes.map((t) => (
              <Badge key={t}>{TRIGGER_LABEL[t] ?? t}</Badge>
            ))}
          </div>

          {cap.health.status === 'error' && cap.health.error && (
            <p
              className="text-[10px] mt-2"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {cap.health.error}
            </p>
          )}

          {cap.has_health_check && (
            <div className="flex justify-end mt-2">
              <button
                type="button"
                onClick={() => void handleRefresh()}
                disabled={refreshing}
                className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
                style={{ color: 'var(--color-text-secondary)' }}
                title="重新检查健康状态"
              >
                <RefreshCw
                  size={10}
                  className={refreshing ? 'animate-spin' : ''}
                />
                刷新状态
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel 主体
// ---------------------------------------------------------------------------

export default function CapabilityPanel() {
  const [items, setItems]       = useState<CapabilityDTO[]>([]);
  const [loading, setLoading]   = useState(false);
  const [error,   setError]     = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCapabilities();
      setItems(data.capabilities);
    } catch (e) {
      const msg = (e as Error).message;
      console.error('[CapabilityPanel] fetch failed:', e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const onCardRefresh = useCallback(async (name: string) => {
    try {
      const res = await runHealthCheck(name);
      setItems((prev) => prev.map((c) =>
        c.name === name ? { ...c, health: res.health } : c,
      ));
    } catch (e) {
      console.error('[CapabilityPanel] healthcheck failed:', e);
    }
  }, []);

  // 按 category 分组（用 useMemo 避免每次渲染重排）。
  const grouped = useMemo(() => {
    const out: Record<string, CapabilityDTO[]> = {};
    for (const cap of items) {
      (out[cap.category] ??= []).push(cap);
    }
    return out;
  }, [items]);

  const categories = Object.keys(grouped).sort();

  return (
    <section
      className="rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-sm font-medium"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          能力 — Momo 能做什么
        </h3>
        <button
          type="button"
          onClick={() => void loadAll()}
          disabled={loading}
          className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
          style={{ color: 'var(--color-text-secondary)' }}
          title="重新拉取 /api/capabilities"
        >
          <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      <p
        className="text-[11px] mb-3"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        每张卡是一个已注册的 capability。绿点=健康；黄=注意；红=异常；灰=
        无 health_check。"谁能调"标记接通方（ChatAgent 主动 / cron 定时 /
        外部 webhook）。
      </p>

      {loading && items.length === 0 ? (
        <p
          className="text-xs py-8 text-center"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          加载中…
        </p>
      ) : error ? (
        <p
          className="text-xs py-8 text-center"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          加载失败：{error}
        </p>
      ) : items.length === 0 ? (
        <p
          className="text-xs py-8 text-center"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          暂无已注册 capability
        </p>
      ) : (
        <div className="space-y-4">
          {categories.map((cat) => (
            <div key={cat}>
              <h4
                className="text-[11px] mb-2 uppercase tracking-wide"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {cat}
              </h4>
              <div className="space-y-2">
                {grouped[cat].map((cap) => (
                  <CapabilityCard
                    key={cap.name}
                    cap={cap}
                    onRefresh={onCardRefresh}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

import { useEffect, useState } from 'react';
import { fetchSystemResources, type SystemResources } from '../../../lib/observability';
import Card from './Card';

/**
 * 2026-06-05 · 救活 SettingsPanelLegacy:1155 起的 SystemStatusSection(已成 orphan
 * 死代码,见 step1 勘察报告)· 拆 card 重排,数据源完全不变:
 *   GET /api/observability/system/resources  · poll 3s · toggle 可暂停。
 *
 * 字段裁剪:
 *   - 移走 Whisper 模型 size / loaded / disk → 归 ModelsCard(语义在那更准)
 *   - 留 Backend RAM/CPU · 系统 RAM% · 网络 ⬇⬆ KB/s
 */
export default function ResourcesCard() {
  const [data, setData] = useState<SystemResources | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetchSystemResources();
        if (!cancelled) setData(r);
      } catch {/* swallow · 网络偶发 · 下次 tick 再试 */}
    };
    void tick();
    if (!autoRefresh) return () => { cancelled = true; };
    const h = setInterval(tick, 3000);
    return () => { cancelled = true; clearInterval(h); };
  }, [autoRefresh]);

  const refreshToggle = (
    <label className="inline-flex items-center gap-1.5 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={autoRefresh}
        onChange={(e) => setAutoRefresh(e.target.checked)}
      />
      <span style={{ color: 'var(--color-text-secondary)' }}>3s 自动刷新</span>
    </label>
  );

  if (!data) {
    return (
      <Card title="📊 资源" rightSlot={refreshToggle}>
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          加载中…
        </div>
      </Card>
    );
  }

  if (!data.has_psutil) {
    return (
      <Card title="📊 资源" rightSlot={refreshToggle}>
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          psutil 未安装 · 后端无法采集系统资源。
        </div>
      </Card>
    );
  }

  const rss     = data.backend_rss_mb ?? 0;
  const totalGB = (data.system_total_ram_mb ?? 0) / 1024;
  const ramPct  = data.system_total_ram_mb ? (rss / data.system_total_ram_mb) * 100 : 0;
  const cpu     = data.backend_cpu_percent ?? 0;
  const sysRam  = data.system_ram_percent ?? 0;

  const Bar = ({ pct, color }: { pct: number; color: string }) => (
    <div className="h-1.5 rounded-full overflow-hidden flex-1"
      style={{ background: 'var(--color-bg-elevated)' }}>
      <div className="h-full rounded-full transition-all"
        style={{ width: `${Math.min(100, pct).toFixed(1)}%`, background: color }} />
    </div>
  );

  return (
    <Card title="📊 资源" rightSlot={refreshToggle}>
      <div className="space-y-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="w-20 shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}>Backend RAM</span>
          <Bar pct={ramPct} color="var(--color-accent)" />
          <span className="font-mono shrink-0 text-right w-24 tabular-nums"
            style={{ color: 'var(--color-text-primary)' }}>
            {rss.toFixed(0)}M / {totalGB.toFixed(1)}G
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="w-20 shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}>Backend CPU</span>
          <Bar pct={cpu} color={cpu > 50 ? 'rgb(245,158,11)' : 'var(--color-accent)'} />
          <span className="font-mono shrink-0 text-right w-24 tabular-nums"
            style={{ color: 'var(--color-text-primary)' }}>
            {cpu.toFixed(1)} %
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="w-20 shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}>系统 RAM</span>
          <Bar pct={sysRam} color="var(--color-text-secondary)" />
          <span className="font-mono shrink-0 text-right w-24 tabular-nums"
            style={{ color: 'var(--color-text-primary)' }}>
            {sysRam.toFixed(0)} %
          </span>
        </div>

        {(data.net_recv_kbps !== null || data.net_sent_kbps !== null) && (
          <div
            className="pt-2 mt-1 flex items-center gap-3 text-[11px]"
            style={{
              borderTop: '1px dashed var(--color-border-subtle)',
              color: 'var(--color-text-secondary)',
            }}
          >
            <span className="font-mono tabular-nums">
              ⬇ {(data.net_recv_kbps ?? 0).toFixed(1)} KB/s
            </span>
            <span className="font-mono tabular-nums">
              ⬆ {(data.net_sent_kbps ?? 0).toFixed(1)} KB/s
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}

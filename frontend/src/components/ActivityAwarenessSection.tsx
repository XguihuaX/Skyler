/**
 * v3.5 chunk 8a — SettingsPanel [活动感知] section。
 *
 * 展示：
 *  - enabled toggle（off → 整套 watcher 停）
 *  - fetch_url_content toggle（off → Momo 知道你在哪个 URL 但不抓正文）
 *  - blocked_apps + blocked_url_patterns 列表（accordion 折叠，编辑增删）
 *  - 当前 state：active_app / browser URL / 上次切换距今多久 + 今日 trigger
 *    用量
 *
 * 与 ExtensionsSection / SettingsPanel 用户档案 section 风格对齐：``<Section>``
 * 包裹 + 内部 padded card。
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Activity, ChevronDown, ChevronRight, Plus, RefreshCw, X,
} from 'lucide-react';
import {
  fetchActivityConfig,
  fetchActivityStatus,
  patchActivityConfig,
  type ActivityConfigResponse,
  type ActivityStatusResponse,
} from '../lib/activity';

interface ActivityAwarenessSectionProps {
  showToast: (text: string) => void;
}

export default function ActivityAwarenessSection({
  showToast,
}: ActivityAwarenessSectionProps) {
  const [cfg, setCfg] = useState<ActivityConfigResponse | null>(null);
  const [status, setStatus] = useState<ActivityStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // accordion state per list
  const [appsOpen, setAppsOpen] = useState(false);
  const [urlsOpen, setUrlsOpen] = useState(false);
  const [newApp, setNewApp] = useState('');
  const [newUrl, setNewUrl] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, s] = await Promise.all([
        fetchActivityConfig(),
        fetchActivityStatus(),
      ]);
      setCfg(c);
      setStatus(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Refresh status every 30s 让 UI 反映当前 active app 切换
  useEffect(() => {
    const id = window.setInterval(() => {
      fetchActivityStatus().then(setStatus).catch(() => {/* ignore */});
    }, 30000);
    return () => window.clearInterval(id);
  }, []);

  const onPatch = async (body: Parameters<typeof patchActivityConfig>[0]) => {
    try {
      const c = await patchActivityConfig(body);
      setCfg(c);
      const s = await fetchActivityStatus();
      setStatus(s);
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`);
    }
  };

  const removeApp = (name: string) => {
    if (!cfg) return;
    void onPatch({ blocked_apps: cfg.blocked_apps.filter((a) => a !== name) });
  };
  const addApp = () => {
    if (!cfg) return;
    const v = newApp.trim();
    if (!v) return;
    if (cfg.blocked_apps.includes(v)) {
      showToast('已存在');
      return;
    }
    setNewApp('');
    void onPatch({ blocked_apps: [...cfg.blocked_apps, v] });
  };
  const removeUrl = (pat: string) => {
    if (!cfg) return;
    void onPatch({
      blocked_url_patterns: cfg.blocked_url_patterns.filter((p) => p !== pat),
    });
  };
  const addUrl = () => {
    if (!cfg) return;
    const v = newUrl.trim();
    if (!v) return;
    if (cfg.blocked_url_patterns.includes(v)) {
      showToast('已存在');
      return;
    }
    setNewUrl('');
    void onPatch({ blocked_url_patterns: [...cfg.blocked_url_patterns, v] });
  };

  return (
    <Section title="活动感知" icon={<Activity size={14} />}>
      {loading && !cfg && (
        <div className="text-xs py-2"
          style={{ color: 'var(--color-text-secondary)' }}>加载中…</div>
      )}
      {error && (
        <div className="text-xs py-2"
          style={{ color: 'rgb(244, 63, 94)' }}>{error}</div>
      )}
      {cfg && status && (
        <>
          {/* 主开关 */}
          <Row label={cfg.enabled
              ? '已启用 — Momo 会感知你切换 app / 浏览器 tab'
              : '已关闭 — Momo 不感知活动'}>
            <Toggle
              value={cfg.enabled}
              onChange={(v) => onPatch({ enabled: v })}
            />
          </Row>

          {/* chunk 8a-ext: 智能陪伴 judge 二级 toggle */}
          <Row
            label={`智能陪伴 — qwen-turbo 判断(${cfg.judge_min_stay_minutes} 分钟停留触发)`}
            hint={
              cfg.judge_enabled
                ? `每 app/URL 停 ${cfg.judge_min_stay_minutes} 分钟自动判断要不要 chime in，受 daily_cap (${cfg.max_daily_triggers}/天) 共享限制`
                : '已关闭：只走 IDE/音乐/技术文档等硬编码 trigger'
            }
          >
            <Toggle
              value={cfg.judge_enabled}
              onChange={(v) => onPatch({ judge_enabled: v })}
            />
          </Row>

          {/* fetch_url_content */}
          <Row
            label="后台抓取公开页面正文"
            hint="启用后 Momo 能看到非黑名单 URL 的页面正文；关闭则只看 URL + 标题"
          >
            <Toggle
              value={cfg.fetch_url_content}
              onChange={(v) => onPatch({ fetch_url_content: v })}
            />
          </Row>

          {/* blocked apps */}
          <Accordion
            title={`黑名单 app（${cfg.blocked_apps.length}）`}
            open={appsOpen}
            onToggle={() => setAppsOpen((x) => !x)}
          >
            {cfg.blocked_apps.map((a) => (
              <ListRow key={a} label={a} onRemove={() => removeApp(a)} />
            ))}
            <AddRow
              value={newApp}
              onChange={setNewApp}
              onAdd={addApp}
              placeholder="例：1Password"
            />
          </Accordion>

          {/* blocked URLs */}
          <Accordion
            title={`黑名单 URL pattern（${cfg.blocked_url_patterns.length}）`}
            open={urlsOpen}
            onToggle={() => setUrlsOpen((x) => !x)}
          >
            {cfg.blocked_url_patterns.map((p) => (
              <ListRow key={p} label={p} onRemove={() => removeUrl(p)} />
            ))}
            <AddRow
              value={newUrl}
              onChange={setNewUrl}
              onAdd={addUrl}
              placeholder="例：*chase.com*"
            />
          </Accordion>

          {/* current state + usage */}
          <div className="mt-3 pt-2 text-xs"
            style={{
              color: 'var(--color-text-secondary)',
              borderTop: '1px dashed var(--color-border-subtle)',
            }}>
            <div>当前状态:</div>
            <div className="pl-2 mt-1 space-y-0.5">
              <div>📱 活跃 app: {status.last_state?.active_app ?? '—'}</div>
              <div>🌐 浏览器: {status.last_state?.browser?.url ?? '—'}</div>
              <div>📝 文档: {status.last_state?.document?.basename ?? '—'}</div>
              <div>🚀 今日 trigger: {status.daily_triggers_today}/{status.daily_cap || '∞'}
                （节流 {status.throttle_minutes} 分钟）</div>
            </div>
            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={() => void refresh()}
                className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
                刷新
              </button>
            </div>
          </div>
        </>
      )}
    </Section>
  );
}


// ---------------------------------------------------------------------------
// Reused small primitives (与 ExtensionsSection / SettingsPanel 同视觉风格)
// ---------------------------------------------------------------------------

function Section({
  title, icon, children,
}: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mb-4">
      <h3 className="text-sm font-semibold mb-2 flex items-center gap-1"
        style={{ color: 'var(--color-text-primary)' }}>
        {icon}{title}
      </h3>
      <div className="rounded-md px-3 py-2"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}>
        {children}
      </div>
    </section>
  );
}

function Row({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1">
      <div className="flex-1 min-w-0">
        <div className="text-xs"
          style={{ color: 'var(--color-text-primary)' }}>{label}</div>
        {hint && (
          <div className="text-[10px] mt-0.5"
            style={{ color: 'var(--color-text-secondary)' }}>{hint}</div>
        )}
      </div>
      {children}
    </div>
  );
}

function Accordion({
  title, open, onToggle, children,
}: { title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="py-1">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-1 text-xs hover:opacity-80"
        style={{ color: 'var(--color-text-primary)' }}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {title}
      </button>
      {open && (
        <div className="mt-1 ml-3 pl-2"
          style={{ borderLeft: '1px dashed var(--color-border-subtle)' }}>
          {children}
        </div>
      )}
    </div>
  );
}

function ListRow({
  label, onRemove,
}: { label: string; onRemove: () => void }) {
  return (
    <div className="flex items-center justify-between py-0.5 text-xs"
      style={{ color: 'var(--color-text-secondary)' }}>
      <span className="font-mono truncate pr-2">• {label}</span>
      <button
        type="button"
        onClick={onRemove}
        className="opacity-60 hover:opacity-100"
        aria-label="移除"
      >
        <X size={10} />
      </button>
    </div>
  );
}

function AddRow({
  value, onChange, onAdd, placeholder,
}: { value: string; onChange: (v: string) => void; onAdd: () => void; placeholder: string }) {
  return (
    <div className="flex items-center gap-1 py-1">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="flex-1 px-1.5 py-0.5 text-[11px] rounded focus:outline-none"
        style={{
          background: 'var(--color-bg-input)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-primary)',
        }}
        onKeyDown={(e) => { if (e.key === 'Enter') onAdd(); }}
      />
      <button
        type="button"
        onClick={onAdd}
        className="px-1.5 py-0.5 text-[10px] rounded hover:opacity-80"
        style={{
          background: 'var(--color-bg-elevated)',
          color: 'var(--color-text-primary)',
          border: '1px solid var(--color-border)',
        }}
      >
        <Plus size={10} />
      </button>
    </div>
  );
}

function Toggle({
  value, onChange,
}: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      className="relative w-11 h-6 rounded-full transition-colors"
      style={{ background: value ? 'var(--color-accent)' : 'var(--color-bg-elevated)' }}
    >
      <span
        className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all ${
          value ? 'left-[22px]' : 'left-0.5'
        }`}
      />
    </button>
  );
}

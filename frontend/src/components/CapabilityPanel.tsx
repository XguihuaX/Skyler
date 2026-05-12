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
  Copy,
  Eye,
  EyeOff,
  Globe,
  Image as ImageIcon,
  Link2,
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
import {
  fetchGoogleStatus,
  revokeGoogleAuth,
  startGoogleAuth,
  triggerTestBriefing,
  type GoogleStatusResponse,
} from '../lib/integrations';
// UX-002：删 MCP banner + 外部 clients section（与 SettingsPanel 底部
// ExtensionsSection (UX-001 + hotfix-6) 信息重复）。原有 fetchMcpClientsStatus
// / fetchMcpServerStatus / reconnectMcpClient / MCPClientStatusItem /
// MCPServerStatus 全部不再 import。
import CapabilityRow from './CapabilityRow';

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
  // v3-G chunk 1.5 — 外部 MCP capability 默认 icon
  'link-2': Link2,
};

function CapabilityIcon({ name }: { name: string }) {
  const Icon = ICON_MAP[name] ?? Circle;
  return <Icon size={14} />;
}


// UX-002：把 cap.description 截到 ~50 字符做 ``briefDescription``（折叠态
// 单行显示）。优先在标点边界截断让短摘要更自然。
function _briefDesc(full: string): string {
  if (!full) return '';
  const limit = 50;
  if (full.length <= limit) return full;
  const slice = full.slice(0, limit);
  // 在标点 / 空格处尾随截断
  const breakAt = Math.max(
    slice.lastIndexOf('，'),
    slice.lastIndexOf('。'),
    slice.lastIndexOf('；'),
    slice.lastIndexOf(' '),
  );
  const cut = breakAt > 20 ? slice.slice(0, breakAt) : slice;
  return cut + '…';
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
  // v3-G chunk 1：Google 集成状态 + 操作回调。仅 calendar.* capability 用。
  googleStatus?: GoogleStatusResponse | null;
  onGoogleAuth?: () => Promise<void>;
  onGoogleRevoke?: () => Promise<void>;
  googleBusy?: boolean;
}

// UX-002: 改 CapabilityCard → CapabilityDetail —— 渲染**展开后**的 body
// (description / consumers / triggers / error / Google footer / refresh)，
// 不再 render header (icon + name + health) 因为那部分已在 CapabilityRow 折
// 叠态显示。整体作为 ``<CapabilityRow expandedContent={<CapabilityDetail ...>} />``
// 的展开内容。
function CapabilityDetail({
  cap,
  onRefresh,
  googleStatus,
  onGoogleAuth,
  onGoogleRevoke,
  googleBusy,
}: CardProps) {
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefresh(cap.name);
    } finally {
      setRefreshing(false);
    }
  };

  // calendar 类 capability 才挂 Google 授权 UI。判别用 category，避免依赖
  // capability name 字符串前缀。
  const isCalendar = cap.category === 'calendar' && !!googleStatus;

  return (
    <div className="py-1">
      {/* category · name + 可选 ext 角标（在展开内容里也保留完整 id，方便复制） */}
      <p
        className="text-[11px]"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {cap.category} · {cap.name}
        {cap.source_server && (
          <span
            className="ml-1.5 inline-flex items-center px-1 rounded text-[9px]"
            style={{
              background: 'var(--color-bg-elevated)',
              border: '1px solid var(--color-border-subtle)',
              color: 'var(--color-text-secondary)',
            }}
            title={`来自外部 MCP server: ${cap.source_server}`}
          >
            [ext · {cap.source_server}]
          </span>
        )}
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

          {/* v3-G chunk 1：calendar 卡 Google 授权 footer */}
          {isCalendar && googleStatus && (
            <div
              className="mt-3 pt-2 flex items-center justify-between gap-2"
              style={{ borderTop: '1px solid var(--color-border-subtle)' }}
            >
              <span
                className="text-[10px]"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {!googleStatus.credentials_present
                  ? 'credentials.json 未放置 — 见 docs/google-calendar-setup.md'
                  : googleStatus.authorized
                    ? `已授权${googleStatus.account_hint ? ' · ' + googleStatus.account_hint.slice(0, 24) : ''}`
                    : '未授权 Google 账号'}
              </span>
              {googleStatus.credentials_present && (
                googleStatus.authorized ? (
                  <button
                    type="button"
                    onClick={() => onGoogleRevoke && void onGoogleRevoke()}
                    disabled={googleBusy}
                    className="text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
                    style={{
                      background: 'var(--color-bg-elevated)',
                      color: 'var(--color-text-primary)',
                      border: '1px solid var(--color-border-subtle)',
                    }}
                  >
                    重新授权
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => onGoogleAuth && void onGoogleAuth()}
                    disabled={googleBusy}
                    className="text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
                    style={{
                      background: 'var(--color-accent)',
                      color: 'var(--color-bubble-user-text)',
                    }}
                    title="弹出浏览器完成 Google OAuth"
                  >
                    {googleBusy ? '授权中…' : '连接 Google'}
                  </button>
                )
              )}
            </div>
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
  );
}

// ---------------------------------------------------------------------------
// Panel 主体
// ---------------------------------------------------------------------------

export default function CapabilityPanel() {
  const [items, setItems]       = useState<CapabilityDTO[]>([]);
  const [loading, setLoading]   = useState(false);
  const [error,   setError]     = useState<string | null>(null);

  // v3-G chunk 1：Google 集成状态。仅给 calendar.* 卡片渲染授权 UI 用。
  const [googleStatus, setGoogleStatus] = useState<GoogleStatusResponse | null>(null);
  const [googleBusy,   setGoogleBusy]   = useState(false);

  // UX-002: 删 mcpServerStatus / mcpClients / mcpReconnectingId state ——
  // 信息搬到 SettingsPanel 底部 ExtensionsSection (UX-001 + hotfix-6) 唯一
  // 入口，不在 CapabilityPanel 顶部 banner 复制。``mcp_external`` category
  // 的 capability（filesystem ×14 + brave-search ×2）仍正常列在 capability
  // 主列表里，用 ``[ext · source_server]`` 角标区分。

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

  const refreshGoogleStatus = useCallback(async () => {
    try {
      const s = await fetchGoogleStatus();
      setGoogleStatus(s);
    } catch (e) {
      console.error('[CapabilityPanel] google status failed:', e);
      // 放空对象避免 calendar 卡片彻底无 footer；UI 文案兜底"credentials 未放置"
      setGoogleStatus({
        credentials_present: false,
        authorized: false,
        account_hint: null,
      });
    }
  }, []);

  // UX-002: 删 refreshMcpServerStatus / refreshMcpClients / onReconnectClient
  // ——MCP server / clients 管理移到 SettingsPanel 底部 ExtensionsSection。

  useEffect(() => {
    void loadAll();
    void refreshGoogleStatus();
  }, [loadAll, refreshGoogleStatus]);

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

  // v3-G chunk 1：触发 OAuth flow。后端 run_local_server 阻塞等浏览器完成。
  // 期间前端把所有 calendar 卡的 [连接 Google] 按钮 disable，避免重复触发。
  const onGoogleAuth = useCallback(async () => {
    setGoogleBusy(true);
    try {
      await startGoogleAuth();
      await refreshGoogleStatus();
      // 授权成功 → 触发整列 health 重检（calendar 卡会从 warn 变 healthy）
      await loadAll();
    } catch (e) {
      console.error('[CapabilityPanel] google auth failed:', e);
    } finally {
      setGoogleBusy(false);
    }
  }, [loadAll, refreshGoogleStatus]);

  const onGoogleRevoke = useCallback(async () => {
    setGoogleBusy(true);
    try {
      await revokeGoogleAuth();
      await refreshGoogleStatus();
      await loadAll();
    } catch (e) {
      console.error('[CapabilityPanel] google revoke failed:', e);
    } finally {
      setGoogleBusy(false);
    }
  }, [loadAll, refreshGoogleStatus]);

  // v3-G chunk 1：起床简报测试。后端 deliver_morning_briefing 会推 notify
  // 到 ws → 前端弹 toast；同时返回 metadata（含合成的 wav 路径），这里把
  // 文本展示出来给用户即时反馈，audio_path 进 console 方便用 afplay 验。
  const [briefingBusy,    setBriefingBusy]    = useState(false);
  const [briefingPreview, setBriefingPreview] = useState<string | null>(null);

  const onTestBriefing = useCallback(async () => {
    setBriefingBusy(true);
    setBriefingPreview(null);
    try {
      const res = await triggerTestBriefing();
      setBriefingPreview(res.text);
      console.info(
        '[briefing test] text=%s audio_path=%s audio_bytes=%d voice_model=%s',
        res.text, res.audio_path, res.audio_bytes, res.voice_model,
      );
    } catch (e) {
      console.error('[CapabilityPanel] briefing test failed:', e);
      setBriefingPreview(`触发失败：${(e as Error).message}`);
    } finally {
      setBriefingBusy(false);
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

      {/*
        UX-002: 删 ``<MCPServerBanner />`` + ``<MCPClientsSection />`` —— MCP
        管理移到 SettingsPanel 底部 ExtensionsSection (UX-001 + hotfix-6) 唯一
        入口。外部 MCP server 暴露的 capability（``mcp_external`` category，
        filesystem ×14 + brave-search ×2）仍在下方 capability 列表里正常显示，
        每行用 ``[ext · source_server]`` 角标区分来源。
      */}

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
              <div className="flex items-center justify-between mb-2">
                <h4
                  className="text-[11px] uppercase tracking-wide flex items-center gap-1.5"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <span>{cat}</span>
                  {/* UX-002：category 级 capability 计数 badge */}
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded normal-case"
                    style={{
                      background: 'var(--color-bg-elevated)',
                      color: 'var(--color-text-secondary)',
                    }}
                  >
                    {grouped[cat].length} cap
                  </span>
                </h4>
                {/* v3-G chunk 1：calendar 类目右侧加测试简报按钮（commit 3
                    会把 Google OAuth 也一并搬到 category header 这一行） */}
                {cat === 'calendar' && (
                  <button
                    type="button"
                    onClick={() => void onTestBriefing()}
                    disabled={briefingBusy}
                    className="text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
                    style={{
                      background: 'var(--color-bg-elevated)',
                      color: 'var(--color-text-primary)',
                      border: '1px solid var(--color-border-subtle)',
                    }}
                    title="立刻触发一次起床简报（v0.1 模板版）"
                  >
                    🧪 {briefingBusy ? '生成中…' : '测试今日简报'}
                  </button>
                )}
              </div>
              {/* 简报触发后，把生成的文本预览出来 */}
              {cat === 'calendar' && briefingPreview && (
                <p
                  className="text-[11px] mb-2 px-2 py-1 rounded"
                  style={{
                    background: 'var(--color-bg-elevated)',
                    color: 'var(--color-text-primary)',
                    border: '1px solid var(--color-border-subtle)',
                  }}
                >
                  {briefingPreview}
                </p>
              )}
              <div
                className="rounded-md px-3"
                style={{
                  background: 'var(--color-bg-surface)',
                  border: '1px solid var(--color-border)',
                }}
              >
                {grouped[cat].map((cap) => (
                  <CapabilityRow
                    key={cap.name}
                    name={cap.name}
                    displayName={cap.display_name}
                    briefDescription={_briefDesc(cap.description)}
                    leftIcon={<CapabilityIcon name={cap.icon} />}
                    statusBadge={
                      <>
                        <HealthDot status={cap.health.status} />
                        <span
                          className="text-[10px]"
                          style={{ color: 'var(--color-text-secondary)' }}
                        >
                          {HEALTH_LABEL[cap.health.status]}
                        </span>
                        {cap.source_server && (
                          <span
                            className="ml-1 inline-flex items-center px-1 rounded text-[9px]"
                            style={{
                              background: 'var(--color-bg-elevated)',
                              border: '1px solid var(--color-border-subtle)',
                              color: 'var(--color-text-secondary)',
                            }}
                            title={`来自外部 MCP server: ${cap.source_server}`}
                          >
                            [ext · {cap.source_server}]
                          </span>
                        )}
                      </>
                    }
                    expandedContent={
                      <CapabilityDetail
                        cap={cap}
                        onRefresh={onCardRefresh}
                        googleStatus={googleStatus}
                        onGoogleAuth={onGoogleAuth}
                        onGoogleRevoke={onGoogleRevoke}
                        googleBusy={googleBusy}
                      />
                    }
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

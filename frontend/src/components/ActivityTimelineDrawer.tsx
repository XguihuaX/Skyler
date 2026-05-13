/**
 * v3.5 chunk 14 — 活动 timeline 抽屉。
 *
 * 跟 MemoryManagerDrawer 同视觉风格(右滑入 60% 宽,backdrop-blur,Escape 关)。
 * 显示当日 session 列表 + 按 app 聚合 + 总活跃时长。可单条删 / 整日清空。
 * 默认显示今天;[<前一天] [后一天>] 可切。
 *
 * 字段语义见 backend/routes/activity_api.py TimelineResponse:
 *   * app_name              hotfix-10 后是英文 bundle 名(Code/Terminal/Safari)
 *   * is_idle_filtered      chunk 8a-ext V2 idle 期间标记,UI [显示/隐藏 idle]
 *   * category              backend 推断(ide/browser/music/video/social/tech_doc/other)
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Calendar, ChevronDown, ChevronLeft, ChevronRight,
  RefreshCw, Trash2, X,
} from 'lucide-react';

import {
  ActivitySessionRow,
  TimelineResponse,
  deleteSession,
  deleteTimelineByDate,
  fetchTimeline,
  formatDuration,
  formatLocalTime,
  todayLocalISO,
} from '../lib/activity_timeline';

interface Props {
  open: boolean;
  onClose: () => void;
  showToast: (text: string) => void;
}

// hotfix-10 _APP_DISPLAY_NAMES 的前端镜像 — UI 显示更友好;
// 与 backend 一致只 map 必要 entries。
const APP_DISPLAY: Record<string, string> = {
  'Code': 'VS Code',
  'Code - Insiders': 'VS Code Insiders',
  'Terminal': '终端',
};

function appDisplay(name: string): string {
  return APP_DISPLAY[name] ?? name;
}

const CATEGORY_LABEL: Record<string, string> = {
  ide: '开发',
  browser: '浏览',
  music: '音乐',
  video: '视频',
  social: '社交',
  tech_doc: '技术文档',
  other: '其他',
};

const CATEGORY_COLOR: Record<string, string> = {
  ide: 'rgb(59, 130, 246)',      // blue
  browser: 'rgb(34, 197, 94)',   // green
  music: 'rgb(168, 85, 247)',    // purple
  video: 'rgb(236, 72, 153)',    // pink
  social: 'rgb(245, 158, 11)',   // amber
  tech_doc: 'rgb(20, 184, 166)', // teal
  other: 'rgb(148, 163, 184)',   // slate
};

function ConfirmDialog({
  open, message, onCancel, onConfirm,
}: {
  open: boolean; message: string;
  onCancel: () => void; onConfirm: () => void;
}) {
  if (!open) return null;
  return (
    <div className="absolute inset-0 z-[60] flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.5)' }}>
      <div className="rounded-md px-4 py-3 w-72 text-xs"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-primary)',
        }}>
        <div className="mb-3">{message}</div>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel}
            className="px-3 py-1.5 rounded-md hover:opacity-80"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
            }}>取消</button>
          <button type="button" onClick={onConfirm}
            className="px-3 py-1.5 rounded-md bg-rose-600 text-white hover:bg-rose-500">
            确认</button>
        </div>
      </div>
    </div>
  );
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function ActivityTimelineDrawer({
  open, onClose, showToast,
}: Props) {
  const [date, setDate] = useState<string>(todayLocalISO());
  const [includeIdle, setIncludeIdle] = useState(true);
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  // UI: app accordion 展开状态(默认全收起,点行展开 sessions list)
  const [openApps, setOpenApps] = useState<Set<string>>(new Set());

  const [pendingDeleteSession, setPendingDeleteSession] = useState<ActivitySessionRow | null>(null);
  const [pendingClearDay, setPendingClearDay] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setErrorText(null);
    try {
      const r = await fetchTimeline({ date, includeIdle });
      setData(r);
    } catch (e) {
      setErrorText((e as Error).message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [date, includeIdle]);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const totalPretty = useMemo(
    () => (data ? formatDuration(data.total_active_seconds) : '—'),
    [data],
  );

  const isToday = date === todayLocalISO();

  const toggleApp = (app: string) => {
    setOpenApps((s) => {
      const next = new Set(s);
      if (next.has(app)) next.delete(app); else next.add(app);
      return next;
    });
  };

  const handleDeleteSession = async (sess: ActivitySessionRow) => {
    setPendingDeleteSession(null);
    try {
      await deleteSession(sess.id);
      await refresh();
      showToast(`已删除 1 条 session`);
    } catch (e) {
      showToast(`删除失败:${(e as Error).message}`);
    }
  };

  const handleClearDay = async () => {
    setPendingClearDay(false);
    try {
      const r = await deleteTimelineByDate(date);
      await refresh();
      showToast(`已清空 ${date}(${r.deleted_count} 条)`);
    } catch (e) {
      showToast(`清空失败:${(e as Error).message}`);
    }
  };

  // Sessions grouped by app (preserves backend ordering — already total desc)
  const sessionsByApp = useMemo(() => {
    const m: Record<string, ActivitySessionRow[]> = {};
    if (!data) return m;
    for (const s of data.sessions) {
      const k = s.app_name;
      if (!m[k]) m[k] = [];
      m[k].push(s);
    }
    return m;
  }, [data]);

  return (
    <div
      className={`fixed inset-0 z-40 ${open ? '' : 'pointer-events-none'}`}
      aria-hidden={!open}
    >
      <div
        className={`absolute inset-0 right-[60%] transition-opacity duration-300 ${
          open ? 'opacity-100' : 'opacity-0'
        }`}
        onClick={onClose}
        aria-label="关闭活动 timeline"
      />

      <div
        className={`absolute top-0 right-0 h-full w-[60%]
                    backdrop-blur-lg shadow-2xl pt-10
                    transition-transform duration-300 ease-out
                    flex flex-col
                    ${open ? 'translate-x-0' : 'translate-x-full'}`}
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 85%, transparent)',
          borderLeft: '1px solid var(--color-border-subtle)',
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
          <div className="flex items-center gap-2">
            <Calendar size={16} style={{ color: 'var(--color-text-primary)' }} />
            <h2 className="text-sm font-semibold"
              style={{ color: 'var(--color-text-primary)' }}>活动 timeline</h2>
          </div>
          <button type="button" onClick={onClose}
            className="opacity-70 hover:opacity-100"
            aria-label="关闭">
            <X size={16} style={{ color: 'var(--color-text-primary)' }} />
          </button>
        </div>

        {/* Date nav + total */}
        <div className="px-4 py-2 flex items-center justify-between gap-2"
          style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => setDate(shiftDate(date, -1))}
              className="px-1 py-1 rounded hover:opacity-80"
              style={{ color: 'var(--color-text-primary)' }}
              aria-label="前一天">
              <ChevronLeft size={14} />
            </button>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="px-1.5 py-0.5 text-xs rounded focus:outline-none"
              style={{
                background: 'var(--color-bg-input)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            />
            <button type="button"
              disabled={isToday}
              onClick={() => setDate(shiftDate(date, 1))}
              className="px-1 py-1 rounded hover:opacity-80 disabled:opacity-30"
              style={{ color: 'var(--color-text-primary)' }}
              aria-label="后一天">
              <ChevronRight size={14} />
            </button>
            {!isToday && (
              <button type="button" onClick={() => setDate(todayLocalISO())}
                className="text-[10px] px-2 py-0.5 rounded ml-1"
                style={{
                  background: 'var(--color-bg-elevated)',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border-subtle)',
                }}>跳到今天</button>
            )}
          </div>
          <div className="text-xs"
            style={{ color: 'var(--color-text-secondary)' }}>
            <span style={{ color: 'var(--color-text-primary)' }}>{totalPretty}</span>
            <span className="ml-2">活跃</span>
          </div>
        </div>

        {/* Controls */}
        <div className="px-4 py-2 flex items-center justify-between text-[11px]"
          style={{
            color: 'var(--color-text-secondary)',
            borderBottom: '1px solid var(--color-border-subtle)',
          }}>
          <label className="inline-flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={includeIdle}
              onChange={(e) => setIncludeIdle(e.target.checked)}
              className="cursor-pointer"
            />
            <span>包含离开期间(idle)</span>
          </label>
          <div className="flex items-center gap-2">
            <button type="button"
              onClick={() => void refresh()}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80">
              <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
            <button type="button"
              onClick={() => setPendingClearDay(true)}
              disabled={!data || data.sessions.length === 0}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-30"
              style={{ color: 'rgb(244, 63, 94)' }}>
              <Trash2 size={10} />
              清空本日
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-3 text-xs"
          style={{ color: 'var(--color-text-primary)' }}>
          {loading && !data && (
            <div className="py-8 text-center text-[11px]"
              style={{ color: 'var(--color-text-secondary)' }}>加载中…</div>
          )}
          {errorText && (
            <div className="py-2 mb-2 px-2 rounded text-[11px]"
              style={{ color: 'rgb(244, 63, 94)', background: 'rgba(244,63,94,0.08)' }}>
              {errorText}
            </div>
          )}
          {data && data.sessions.length === 0 && !loading && (
            <div className="py-8 text-center text-[11px]"
              style={{ color: 'var(--color-text-secondary)' }}>
              {date} 暂无活动记录
            </div>
          )}

          {/* Category summary 横条(只在有数据时) */}
          {data && data.sessions.length > 0 && (
            <div className="mb-3">
              <div className="text-[10px] mb-1"
                style={{ color: 'var(--color-text-secondary)' }}>类别分布</div>
              <div className="flex h-2 rounded-full overflow-hidden"
                style={{ background: 'var(--color-bg-elevated)' }}>
                {Object.entries(data.summary_by_category)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cat, secs]) => (
                    <div key={cat}
                      style={{
                        width: `${(secs / data.total_active_seconds) * 100}%`,
                        background: CATEGORY_COLOR[cat] ?? CATEGORY_COLOR.other,
                      }}
                      title={`${CATEGORY_LABEL[cat] ?? cat} ${formatDuration(secs)}`}
                    />
                  ))}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px]"
                style={{ color: 'var(--color-text-secondary)' }}>
                {Object.entries(data.summary_by_category)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cat, secs]) => (
                    <span key={cat} className="inline-flex items-center gap-1">
                      <span className="w-2 h-2 rounded-sm"
                        style={{ background: CATEGORY_COLOR[cat] ?? CATEGORY_COLOR.other }} />
                      {CATEGORY_LABEL[cat] ?? cat} {formatDuration(secs)}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* App accordion list */}
          {data && data.summary_by_app.map((appSum) => {
            const sessions = sessionsByApp[appSum.app_name] ?? [];
            const isOpen = openApps.has(appSum.app_name);
            const catColor = CATEGORY_COLOR[appSum.category ?? 'other'] ?? CATEGORY_COLOR.other;
            return (
              <div key={appSum.app_name} className="mb-1 rounded-md"
                style={{
                  border: '1px solid var(--color-border-subtle)',
                  background: 'color-mix(in srgb, var(--color-bg-elevated) 50%, transparent)',
                }}>
                <button
                  type="button"
                  onClick={() => toggleApp(appSum.app_name)}
                  className="w-full px-2 py-1.5 flex items-center justify-between text-left hover:opacity-90">
                  <div className="flex items-center gap-2 min-w-0">
                    {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <span className="w-2 h-2 rounded-sm flex-shrink-0"
                      style={{ background: catColor }} />
                    <span className="font-medium truncate">
                      {appDisplay(appSum.app_name)}
                    </span>
                    <span className="text-[10px] flex-shrink-0"
                      style={{ color: 'var(--color-text-secondary)' }}>
                      ({appSum.session_count})
                    </span>
                  </div>
                  <span className="text-[11px] ml-2 flex-shrink-0">
                    {formatDuration(appSum.total_seconds)}
                  </span>
                </button>
                {isOpen && (
                  <div className="px-2 pb-1.5 pt-0.5"
                    style={{ borderTop: '1px dashed var(--color-border-subtle)' }}>
                    {sessions.map((s) => (
                      <div key={s.id}
                        className="flex items-center justify-between py-0.5 group">
                        <div className="flex-1 min-w-0">
                          <span className="text-[10px]"
                            style={{ color: 'var(--color-text-secondary)' }}>
                            {formatLocalTime(s.start_at)}–{formatLocalTime(s.end_at)}
                          </span>
                          {s.browser_url && (
                            <span className="ml-2 truncate text-[11px]"
                              style={{ color: 'var(--color-text-primary)' }}>
                              {s.browser_title || s.browser_url}
                            </span>
                          )}
                          {s.is_idle_filtered && (
                            <span className="ml-1 text-[9px] px-1 py-0 rounded"
                              style={{
                                background: 'rgba(245,158,11,0.15)',
                                color: 'rgb(245,158,11)',
                              }}>
                              idle
                            </span>
                          )}
                        </div>
                        <span className="text-[10px] mx-2 flex-shrink-0"
                          style={{ color: 'var(--color-text-secondary)' }}>
                          {formatDuration(s.duration_seconds)}
                        </span>
                        <button
                          type="button"
                          onClick={() => setPendingDeleteSession(s)}
                          className="opacity-0 group-hover:opacity-60 hover:!opacity-100"
                          aria-label="删除此 session">
                          <Trash2 size={11} />
                        </button>
                      </div>
                    ))}
                    {/* Top URLs note */}
                    {appSum.top_urls.length > 0 && (
                      <div className="pt-1 mt-1 text-[9px]"
                        style={{
                          color: 'var(--color-text-secondary)',
                          borderTop: '1px dotted var(--color-border-subtle)',
                        }}>
                        Top URL: <span className="font-mono">
                          {(() => {
                            const u = appSum.top_urls[0].url;
                            try { return u.split('//')[1].split('/')[0]; }
                            catch { return u; }
                          })()}
                        </span> ({formatDuration(appSum.top_urls[0].seconds)})
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Confirm dialogs */}
        <ConfirmDialog
          open={pendingDeleteSession !== null}
          message={
            pendingDeleteSession
              ? `删除这条 session?\n${appDisplay(pendingDeleteSession.app_name)} · ${formatDuration(pendingDeleteSession.duration_seconds)}`
              : ''
          }
          onCancel={() => setPendingDeleteSession(null)}
          onConfirm={() => pendingDeleteSession && handleDeleteSession(pendingDeleteSession)}
        />
        <ConfirmDialog
          open={pendingClearDay}
          message={`清空 ${date} 整日活动记录?此操作不可撤销。`}
          onCancel={() => setPendingClearDay(false)}
          onConfirm={handleClearDay}
        />
      </div>
    </div>
  );
}


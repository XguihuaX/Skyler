import { useCallback, useEffect, useState } from 'react';
import { useAppStore, type ThemeKey } from '../store';
import { setConfigField } from '../lib/window';
import { toggleConfigField } from '../lib/toggleConfig';
// bugfix-3.3: lib/models.ts 已下线 (旧 /api/settings/model 路径)。LLM 切换走
// DB ai_providers; 这个 legacy 面板里的 ModelSection 一并删除。
import {
  triggerTestBriefing,
  resetCharacterState,
  fetchClipboardEnabled,
  setClipboardEnabled,
  type ClipboardItem,
} from '../lib/integrations';
import CapabilityPanel from './CapabilityPanel';
import ExtensionsSection from './ExtensionsSection';
import ActivityAwarenessSection from './ActivityAwarenessSection';
import ActivityTimelineDrawer from './ActivityTimelineDrawer';
import MemoryManagerDrawer from './MemoryManagerDrawer';
import UserProfileSection from './UserProfileSection';

const BACKEND_BASE = 'http://127.0.0.1:8000';

// 2026-06-05 · ASR/VAD LS keys(recordingMode / vadPositiveThreshold /
// vadRedemptionMs / muteWhileSpeaking)随 dead SettingsPanel default 一起删,
// 现在由 store/index.ts 自带读写。
// v3.5 chunk 5b:启动入场视频开关 LS,SplashSection 仍在用。
const LS_SPLASH_ENABLED   = 'momoos.splashEnabled';

/**
 * hotfix-7: 把任何 reject 类型(Error / string / unknown)归一成可读 msg,
 * 不让 toast 显示 "undefined"。setConfigField 本身已 normalize 一次,本函数
 * 是双保险给 catch 路径用。
 */
function extractErrorMessage(e: unknown): string {
  if (typeof e === 'string') return e || '未知错误';
  if (e instanceof Error) return e.message || '未知错误';
  if (e && typeof e === 'object') {
    try {
      const j = JSON.stringify(e);
      return j === '{}' ? '未知错误' : j;
    } catch { /* ignore */ }
  }
  return String(e ?? '未知错误');
}

interface ToggleProps {
  label: string;
  value: boolean;
  onChange: (next: boolean) => void;
}

function Toggle({ label, value, onChange }: ToggleProps) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
        {label}
      </span>
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
    </div>
  );
}

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}

function Segmented<T extends string>({ label, value, options, onChange }: SegmentedProps<T>) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
        {label}
      </span>
      <div
        className="inline-flex rounded-md p-0.5"
        style={{
          background: 'var(--color-bg-input)',
          border: '1px solid var(--color-border)',
        }}
      >
        {options.map((opt) => {
          const active = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              className="px-3 py-1 text-xs rounded-md transition-colors"
              style={
                active
                  ? {
                      background: 'var(--color-accent)',
                      color: 'var(--color-bubble-user-text)',
                    }
                  : { color: 'var(--color-text-primary)' }
              }
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  onChange: (v: number) => void;
}

function Slider({ label, value, min, max, step, display, onChange }: SliderProps) {
  return (
    <div className="py-2">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
          {label}
        </span>
        <span
          className="text-xs tabular-nums"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {display}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full"
        style={{ accentColor: 'var(--color-accent)' }}
      />
    </div>
  );
}

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <section
      className="mb-4 rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <h3
        className="text-sm font-medium mb-2"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {title}
      </h3>
      <div
        className="divide-y"
        style={{ borderColor: 'var(--color-border-subtle)' }}
      >
        {children}
      </div>
    </section>
  );
}


// bugfix-4 (4.4): 折叠"进阶设置"块,把不常改的字段藏起来减视觉噪。
function CollapsibleAdvanced({
  label, children,
}: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="py-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between text-xs py-1"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        <span>⚙ {label}</span>
        <span>{open ? '▼' : '▶'}</span>
      </button>
      {open && (
        <div className="pl-3"
          style={{ borderLeft: '2px solid var(--color-border-subtle)' }}>
          {children}
        </div>
      )}
    </div>
  );
}

interface ToastInfo {
  id: number;
  text: string;
}

// ---------------------------------------------------------------------------
// Memory section — summary card + manager-drawer launcher
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// v3-G chunk 2 / 2.6 — 主动陪伴 (Proactive Companionship) section
// ---------------------------------------------------------------------------
//
// chunk 2.6: mode 三选一 radio (wake_call / morning_briefing / off)。下方
// 根据选中模式条件渲染该模式的参数。test 按钮按当前模式路由到对应 trigger。

interface ProactiveSectionProps {
  showToast: (text: string) => void;
}

interface ModeRadioProps {
  value: ProactiveModeAlias;
  onChange: (next: ProactiveModeAlias) => void;
}

type ProactiveModeAlias = 'wake_call' | 'morning_briefing' | 'off';

function ModeRadio({ value, onChange }: ModeRadioProps) {
  const opts: { id: ProactiveModeAlias; title: string; desc: string }[] = [
    { id: 'wake_call',        title: '叫醒模式（推荐）',  desc: 'cron 短问候，你回应后才告诉你今日要事' },
    { id: 'morning_briefing', title: '整段播报模式',      desc: 'cron 自动播 200-300 字简报' },
    { id: 'off',              title: '关闭',              desc: '不主动开口' },
  ];
  return (
    <div className="py-2 space-y-2">
      {opts.map((o) => {
        const active = value === o.id;
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => onChange(o.id)}
            className="w-full text-left px-3 py-2 rounded transition-colors"
            style={{
              background: active
                ? 'color-mix(in srgb, var(--color-accent) 15%, transparent)'
                : 'var(--color-bg-input)',
              border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
            }}
          >
            <div className="flex items-center gap-2">
              <span
                className="inline-block w-3 h-3 rounded-full"
                style={{
                  background: active ? 'var(--color-accent)' : 'transparent',
                  border: '1px solid var(--color-accent)',
                }}
              />
              <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                {o.title}
              </span>
            </div>
            <div className="text-xs ml-5 mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              {o.desc}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// bugfix-2: 导出供 SettingsPanelV2 / CapabilitiesPanel 复用,不动函数体。
export function ProactiveSection({ showToast }: ProactiveSectionProps) {
  const proactiveEnabled        = useAppStore((s) => s.proactiveEnabled);
  const setProactiveEnabled     = useAppStore((s) => s.setProactiveEnabled);
  const proactiveMode           = useAppStore((s) => s.proactiveMode);
  const setProactiveMode        = useAppStore((s) => s.setProactiveMode);
  const morningBriefingCron     = useAppStore((s) => s.morningBriefingCron);
  const setMorningBriefingCron  = useAppStore((s) => s.setMorningBriefingCron);
  const morningBriefingCity     = useAppStore((s) => s.morningBriefingCity);
  const setMorningBriefingCity  = useAppStore((s) => s.setMorningBriefingCity);
  const wakeCallCron            = useAppStore((s) => s.wakeCallCron);
  const setWakeCallCron         = useAppStore((s) => s.setWakeCallCron);
  const wakeCallPendingTtl      = useAppStore((s) => s.wakeCallPendingTtlMinutes);
  const setWakeCallPendingTtl   = useAppStore((s) => s.setWakeCallPendingTtlMinutes);
  const wakeCallSnoozeMin       = useAppStore((s) => s.wakeCallDefaultSnoozeMinutes);
  const setWakeCallSnoozeMin    = useAppStore((s) => s.setWakeCallDefaultSnoozeMinutes);
  const wakeCallCity            = useAppStore((s) => s.wakeCallCity);
  const setWakeCallCity         = useAppStore((s) => s.setWakeCallCity);
  const proactiveCharOverride   = useAppStore((s) => s.proactiveCharOverride);
  const setProactiveCharOverride = useAppStore((s) => s.setProactiveCharOverride);
  const characters              = useAppStore((s) => s.characters);

  const [morningCronDraft, setMorningCronDraft] = useState<string>(morningBriefingCron);
  const [morningCityDraft, setMorningCityDraft] = useState<string>(morningBriefingCity);
  const [wakeCronDraft,    setWakeCronDraft]    = useState<string>(wakeCallCron);
  const [wakeCityDraft,    setWakeCityDraft]    = useState<string>(wakeCallCity);
  const [wakeTtlDraft,     setWakeTtlDraft]     = useState<string>(String(wakeCallPendingTtl));
  const [wakeSnoozeDraft,  setWakeSnoozeDraft]  = useState<string>(String(wakeCallSnoozeMin));
  const [busyTesting, setBusyTesting] = useState(false);

  useEffect(() => { setMorningCronDraft(morningBriefingCron); }, [morningBriefingCron]);
  useEffect(() => { setMorningCityDraft(morningBriefingCity); }, [morningBriefingCity]);
  useEffect(() => { setWakeCronDraft(wakeCallCron); }, [wakeCallCron]);
  useEffect(() => { setWakeCityDraft(wakeCallCity); }, [wakeCallCity]);
  useEffect(() => { setWakeTtlDraft(String(wakeCallPendingTtl)); }, [wakeCallPendingTtl]);
  useEffect(() => { setWakeSnoozeDraft(String(wakeCallSnoozeMin)); }, [wakeCallSnoozeMin]);

  const writeField = useCallback(
    (keyPath: string, value: unknown, label: string, rollback: () => void) => {
      setConfigField(keyPath, value).catch((e: unknown) => {
        console.error(`[Proactive] ${keyPath} sync failed:`, e);
        rollback();
        // hotfix-7: extractErrorMessage 兜底,不让 Tauri Rust Err(string)
        // shape 让 toast 显示 "undefined"
        showToast(`${label} 写入失败：${extractErrorMessage(e)}`);
      });
    },
    [showToast],
  );

  const onToggleProactive = (next: boolean) => {
    const prev = proactiveEnabled;
    setProactiveEnabled(next);
    writeField('proactive.enabled', next, '主动陪伴总开关', () => setProactiveEnabled(prev));
  };

  const onChangeMode = (next: ProactiveModeAlias) => {
    if (next === proactiveMode) return;
    const prev = proactiveMode;
    setProactiveMode(next);
    writeField('proactive.mode', next, '主动陪伴模式', () => setProactiveMode(prev));
  };

  const commitTextField = (
    draft: string, current: string,
    setStore: (v: string) => void, setDraft: (v: string) => void,
    keyPath: string, label: string,
  ) => {
    const value = draft.trim();
    if (!value || value === current) { setDraft(current); return; }
    const prev = current;
    setStore(value);
    writeField(keyPath, value, label, () => { setStore(prev); setDraft(prev); });
  };

  const commitIntField = (
    draft: string, current: number, minVal: number, maxVal: number,
    setStore: (v: number) => void, setDraft: (v: string) => void,
    keyPath: string, label: string,
  ) => {
    const parsed = parseInt(draft, 10);
    if (!Number.isFinite(parsed) || parsed < minVal || parsed > maxVal) {
      setDraft(String(current));
      showToast(`${label} 必须在 ${minVal}-${maxVal} 之间`);
      return;
    }
    if (parsed === current) return;
    const prev = current;
    setStore(parsed);
    writeField(keyPath, parsed, label, () => { setStore(prev); setDraft(String(prev)); });
  };

  const onCharOverride = (raw: string) => {
    const next = raw === '' ? null : Number(raw);
    const prev = proactiveCharOverride;
    setProactiveCharOverride(next);
    writeField(
      'proactive.character_id_override', next, '角色覆盖',
      () => setProactiveCharOverride(prev),
    );
  };

  const onTestBriefing = async () => {
    if (busyTesting) return;
    setBusyTesting(true);
    try {
      const apiMode = proactiveMode === 'wake_call' ? 'wake_call'
                    : proactiveMode === 'morning_briefing' ? 'morning'
                    : 'auto';
      const r = await triggerTestBriefing(apiMode);
      const preview = (r.text || '').slice(0, 40);
      showToast(`触发成功：${preview}${r.text.length > 40 ? '…' : ''}`);
    } catch (e) {
      showToast(`触发失败：${(e as Error).message}`);
    } finally {
      setBusyTesting(false);
    }
  };

  const inputCls = 'w-full px-2 py-1.5 text-xs rounded font-mono';
  const inputStyle = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  } as const;

  return (
    <Section title="主动陪伴">
      <Toggle
        label="启用主动陪伴"
        value={proactiveEnabled}
        onChange={onToggleProactive}
      />

      <ModeRadio value={proactiveMode} onChange={onChangeMode} />

      {proactiveMode === 'wake_call' && (
        <>
          {/* bugfix-4 (4.4): 术语 polish — 英文 jargon (Pending TTL / Snooze) 改
              友好中文,加 "进阶设置" 折叠分组减视觉噪。 */}
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>叫醒时间</span>
              <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {wakeCallCron === '0 8 * * *' ? '每天 8:00' : 'cron 自定义'}
              </span>
            </div>
            <input
              type="text" value={wakeCronDraft} placeholder="0 8 * * * (cron 表达式)"
              onChange={(e) => setWakeCronDraft(e.target.value)}
              onBlur={() => commitTextField(
                wakeCronDraft, wakeCallCron, setWakeCallCron, setWakeCronDraft,
                'proactive.wake_call_briefing.cron', '叫醒时间',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className={inputCls} style={inputStyle}
            />
            <div className="text-[10px] mt-0.5"
              style={{ color: 'var(--color-text-secondary)' }}>
              cron 5 字段:分 时 日 月 星期。eg ``0 8 * * *`` = 每天 8:00。
            </div>
          </div>
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                所在城市
              </span>
              <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                天气查询用
              </span>
            </div>
            <input
              type="text" value={wakeCityDraft} placeholder="东京"
              onChange={(e) => setWakeCityDraft(e.target.value)}
              onBlur={() => commitTextField(
                wakeCityDraft, wakeCallCity, setWakeCallCity, setWakeCityDraft,
                'proactive.wake_call_briefing.city', '城市',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className="w-full px-2 py-1.5 text-xs rounded" style={inputStyle}
            />
          </div>
          {/* bugfix-4 (4.4): 进阶设置折叠 — TTL / Snooze 默认不暴露 */}
          <CollapsibleAdvanced label="进阶设置 (等待时长 / 稍后提醒)">
            <div className="py-2">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                  等待响应时长 (分钟)
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  叫醒后多久内回应触发简报
                </span>
              </div>
              <input
                type="text" value={wakeTtlDraft} placeholder="30"
                onChange={(e) => setWakeTtlDraft(e.target.value)}
                onBlur={() => commitIntField(
                  wakeTtlDraft, wakeCallPendingTtl, 5, 240,
                  setWakeCallPendingTtl, setWakeTtlDraft,
                  'proactive.wake_call_briefing.pending_ttl_minutes', '等待响应时长',
                )}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                className={inputCls} style={inputStyle}
              />
            </div>
            <div className="py-2">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                  稍后提醒默认 (分钟)
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  用户说"再睡"未指定时长时
                </span>
              </div>
              <input
                type="text" value={wakeSnoozeDraft} placeholder="30"
                onChange={(e) => setWakeSnoozeDraft(e.target.value)}
                onBlur={() => commitIntField(
                  wakeSnoozeDraft, wakeCallSnoozeMin, 5, 120,
                  setWakeCallSnoozeMin, setWakeSnoozeDraft,
                  'proactive.wake_call_briefing.default_snooze_minutes', '稍后提醒默认',
                )}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                className={inputCls} style={inputStyle}
              />
            </div>
          </CollapsibleAdvanced>
        </>
      )}

      {proactiveMode === 'morning_briefing' && (
        <>
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>简报时间</span>
              <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {morningBriefingCron === '0 9 * * *' ? '每天 9:00' : 'cron 自定义'}
              </span>
            </div>
            <input
              type="text" value={morningCronDraft} placeholder="0 9 * * * (cron 表达式)"
              onChange={(e) => setMorningCronDraft(e.target.value)}
              onBlur={() => commitTextField(
                morningCronDraft, morningBriefingCron,
                setMorningBriefingCron, setMorningCronDraft,
                'proactive.morning_briefing.cron', '简报时间',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className={inputCls} style={inputStyle}
            />
            <div className="text-[10px] mt-0.5"
              style={{ color: 'var(--color-text-secondary)' }}>
              cron 5 字段:分 时 日 月 星期。eg ``0 9 * * *`` = 每天 9:00。
            </div>
          </div>
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                城市（用于天气查询）
              </span>
            </div>
            <input
              type="text" value={morningCityDraft} placeholder="东京"
              onChange={(e) => setMorningCityDraft(e.target.value)}
              onBlur={() => commitTextField(
                morningCityDraft, morningBriefingCity,
                setMorningBriefingCity, setMorningCityDraft,
                'proactive.morning_briefing.city', '城市',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className="w-full px-2 py-1.5 text-xs rounded" style={inputStyle}
            />
          </div>
        </>
      )}

      <div className="py-2">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>角色覆盖</span>
        </div>
        <select
          value={proactiveCharOverride === null ? '' : String(proactiveCharOverride)}
          onChange={(e) => onCharOverride(e.target.value)}
          className="w-full px-2 py-1.5 text-xs rounded"
          style={inputStyle}
        >
          <option value="">自动跟随最近活跃</option>
          {characters.map((c) => (
            <option key={c.id} value={String(c.id)}>{c.name}</option>
          ))}
        </select>
      </div>

      <div className="py-2 flex justify-end">
        <button
          type="button"
          onClick={onTestBriefing}
          disabled={busyTesting || proactiveMode === 'off'}
          className="text-xs px-3 py-1.5 rounded transition-colors"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-bubble-user-text)',
            opacity: busyTesting || proactiveMode === 'off' ? 0.5 : 1,
          }}
        >
          🧪 立即测试{proactiveMode === 'wake_call' ? '叫醒' : '简报'}
        </button>
      </div>
    </Section>
  );
}


// ---------------------------------------------------------------------------
// v3-G chunk 3a — 剪贴板 section
// ---------------------------------------------------------------------------

interface ClipboardSectionProps {
  showToast: (text: string) => void;
}

// bugfix-2.2: 导出供 SettingsPanelV2 复用。
export function ClipboardSection({ showToast }: ClipboardSectionProps) {
  const [enabled, setEnabled] = useState(true);
  const [items, setItems] = useState<ClipboardItem[]>([]);
  const [loading, setLoading] = useState(false);
  // UX-005: 预览列表默认收起,与 UX-003 三层 accordion 视觉一致 — 用户点击
  // header 才展开。轮询 5s 不动(列表收起也继续更新,展开后立刻看到最新)。
  const [listExpanded, setListExpanded] = useState(false);

  // v3-G chunk 4 Part B: 启动时同步真实后端状态（不依赖 localStorage）
  useEffect(() => {
    fetchClipboardEnabled()
      .then((v) => setEnabled(v))
      .catch((e) => console.warn('[clipboard] fetch enabled failed:', e));
  }, []);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/clipboard/recent?n=5');
      if (res.ok) {
        const data = await res.json();
        setItems((data?.items ?? []) as ClipboardItem[]);
      }
    } catch (e) {
      console.warn('[clipboard section] fetch failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  // mount + 5s 轮询：对齐后端 1Hz polling 的延迟体验（用户复制后 ~5s 内可见）
  useEffect(() => {
    fetchItems();
    const t = setInterval(fetchItems, 5000);
    return () => clearInterval(t);
  }, [fetchItems]);

  const onClearAll = async () => {
    try {
      const res = await fetch('http://127.0.0.1:8000/api/clipboard/clear', {
        method: 'POST',
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      setItems([]);
      showToast('剪贴板已清空');
    } catch (e) {
      showToast(`清空失败：${(e as Error).message}`);
    }
  };

  const onPreview = (item: ClipboardItem) => {
    const preview = item.content.length > 200
      ? item.content.slice(0, 200) + '…'
      : item.content;
    alert(preview);
  };

  return (
    <Section title="剪贴板">
      <Toggle
        label="捕获剪贴板（默认开启）"
        value={enabled}
        onChange={(v) => {
          // v3-G chunk 4 Part B: 真接通后端 ClipboardWatcher.set_enabled
          // 通过 POST /api/clipboard/enabled。runtime override；重启回 yaml 默认。
          const prev = enabled;
          setEnabled(v);
          setClipboardEnabled(v).catch((e) => {
            console.error('[clipboard] toggle sync failed:', e);
            setEnabled(prev);
            showToast(`剪贴板开关写入失败：${(e as Error).message}`);
          });
        }}
      />
      <div
        className="text-xs py-1.5"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        🔒 剪贴板内容仅本地内存，重启清空，不外传。
      </div>

      {/* UX-005: 预览列表 accordion 折叠化 — header 点击 toggle,默认收起。
          视觉与 UX-003 三层 accordion 二级 ProviderGroupRow 一致。 */}
      <div className="py-2">
        <button
          type="button"
          onClick={() => setListExpanded((v) => !v)}
          className="w-full flex items-center justify-between text-xs py-1.5 px-1 rounded hover:opacity-80"
          style={{ color: 'var(--color-text-secondary)' }}
          aria-expanded={listExpanded}
        >
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 text-center">
              {listExpanded ? '▾' : '▸'}
            </span>
            <span>📋 最近 {items.length} 条</span>
          </span>
          {listExpanded && (
            <span className="flex gap-2"
              onClick={(e) => e.stopPropagation()}>
              {/* stopPropagation:UX-003 教训防按钮 click 冒泡触发折叠 toggle */}
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); void fetchItems(); }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    e.stopPropagation();
                    void fetchItems();
                  }
                }}
                className="text-xs px-2 py-1 rounded cursor-pointer"
                style={{
                  background: 'var(--color-bg-input)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                  opacity: loading ? 0.5 : 1,
                }}
              >
                {loading ? '…' : '↻ 刷新'}
              </span>
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); void onClearAll(); }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    e.stopPropagation();
                    void onClearAll();
                  }
                }}
                className="text-xs px-2 py-1 rounded cursor-pointer"
                style={{
                  background: 'var(--color-bg-input)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
              >
                全部清除
              </span>
            </span>
          )}
        </button>

        {listExpanded && (
          <div className="mt-1.5">
            {items.length === 0 ? (
              <div
                className="text-xs italic py-2"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                （还没捕获到剪贴板内容；复制点东西试试）
              </div>
            ) : (
              <ul className="space-y-1.5">
                {items.map((it) => (
                  <li
                    key={it.captured_at}
                    className="text-xs px-2 py-1.5 rounded cursor-pointer hover:opacity-80"
                    style={{
                      background: 'var(--color-bg-input)',
                      border: '1px solid var(--color-border-subtle)',
                      color: 'var(--color-text-primary)',
                    }}
                    title={it.content}
                    onClick={() => onPreview(it)}
                  >
                    <div className="flex items-center justify-between">
                      <span
                        className="text-[10px] uppercase tabular-nums"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        {it.content_type}
                      </span>
                      <span
                        className="text-[10px]"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        {(it.captured_iso || '').slice(11, 19)}
                      </span>
                    </div>
                    <div className="truncate">{it.content}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}


// ---------------------------------------------------------------------------
// v3-G chunk 3b — 角色状态 section
// ---------------------------------------------------------------------------

interface CharacterStateSectionProps {
  showToast: (text: string) => void;
}

// bugfix-2.2: 导出供 SettingsPanelV2 复用。
export function CharacterStateSection({ showToast }: CharacterStateSectionProps) {
  const showPanel        = useAppStore((s) => s.showCharacterStatePanel);
  const setShowPanel     = useAppStore((s) => s.setShowCharacterStatePanel);
  const characterId      = useAppStore((s) => s.currentCharacterId);
  const setState         = useAppStore((s) => s.setCurrentCharacterState);
  const [confirmReset, setConfirmReset] = useState(false);

  const onReset = async () => {
    if (characterId == null) {
      showToast('当前角色未选定');
      setConfirmReset(false);
      return;
    }
    try {
      const r = await resetCharacterState(characterId);
      setState(r);
      showToast(`已重置：mood=neutral, intimacy=0`);
    } catch (e) {
      showToast(`重置失败：${(e as Error).message}`);
    } finally {
      setConfirmReset(false);
    }
  };

  return (
    <>
      <Section title="角色状态">
        <Toggle
          label="显示状态条"
          value={showPanel}
          onChange={setShowPanel}
        />
        <div
          className="text-xs py-1.5"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          状态条右下角显示当前 mood + 亲密度，hover 看 thought / activity。
        </div>
        <div className="py-2 flex justify-end">
          <button
            type="button"
            onClick={() => setConfirmReset(true)}
            disabled={characterId == null}
            className="text-xs px-3 py-1.5 rounded transition-colors"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
              opacity: characterId == null ? 0.5 : 1,
            }}
          >
            重置亲密度
          </button>
        </div>
      </Section>
      {confirmReset && (
        <ConfirmModal
          text={'确认重置当前角色的 mood / intimacy / thought / activity 到出厂默认？\n（将影响 Momo 对你的态度起点）'}
          onConfirm={onReset}
          onCancel={() => setConfirmReset(false)}
        />
      )}
    </>
  );
}


interface ConfirmModalProps {
  text: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmModal({ text, onConfirm, onCancel }: ConfirmModalProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onCancel}
    >
      <div
        className="rounded-lg p-5 w-80 shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <p
          className="text-sm mb-4 whitespace-pre-line"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {text}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-md transition"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded-md bg-rose-600 text-white hover:bg-rose-500 transition"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}

interface MemorySectionProps {
  userId: string;
  characterId: number | null;
  showToast: (text: string) => void;
  managerOpen: boolean;
  onOpenManager: () => void;
  onCountChange: (count: number) => void;
  count: number | null;
}

// ---------------------------------------------------------------------------
// v3.5 chunk 14 — Activity timeline section
//
// 与 MemorySection 同 layout(标题 + 单卡片 + 主按钮),只暴露"打开 timeline"
// 入口。记录开关 / 黑名单 / idle 阈值 共享上方 ActivityAwarenessSection,
// 不重复 toggle 避免 UI 噪音。
// ---------------------------------------------------------------------------


interface ActivityTimelineSectionProps {
  onOpenTimeline: () => void;
}


// bugfix-2.2: 导出供 SettingsPanelV2 复用。
export function ActivityTimelineSection({ onOpenTimeline }: ActivityTimelineSectionProps) {
  return (
    <section
      className="mb-4 rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <h3
        className="text-sm font-medium mb-3"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        活动记录
      </h3>
      <div
        className="flex items-center justify-between p-4 rounded-lg"
        style={{ background: 'color-mix(in srgb, var(--color-bg-surface) 40%, transparent)' }}
      >
        <div className="flex flex-col">
          <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
            每日活动 timeline
          </span>
          <span className="text-[11px] mt-0.5"
            style={{ color: 'var(--color-text-secondary)' }}>
            跟聊天记录平行的活动 timeline,Momo 能引用今天做了什么
          </span>
        </div>
        <button
          type="button"
          onClick={onOpenTimeline}
          className="px-3 py-1.5 text-xs rounded-md transition"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-bubble-user-text)',
          }}
        >
          查看
        </button>
      </div>
    </section>
  );
}


// bugfix-2.2: 导出供 SettingsPanelV2 复用。
export function MemorySection({
  userId,
  characterId,
  showToast,
  managerOpen,
  onOpenManager,
  onCountChange,
  count,
}: MemorySectionProps) {
  const [pendingClearAll, setPendingClearAll] = useState(false);

  const buildListUrl = useCallback(() => {
    const params = new URLSearchParams({ user_id: userId });
    if (characterId !== null) params.set('character_id', String(characterId));
    return `${BACKEND_BASE}/api/memory/list?${params.toString()}`;
  }, [userId, characterId]);

  const fetchCount = useCallback(async () => {
    try {
      const r = await fetch(buildListUrl());
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as { id: number }[];
      onCountChange(data.length);
    } catch (e) {
      console.error('[MemorySection] count fetch failed:', e);
      showToast(`记忆条数加载失败：${(e as Error).message}`);
      onCountChange(0);
    }
  }, [buildListUrl, onCountChange, showToast]);

  // Refresh on mount, when character switches, and when the manager drawer
  // closes so the summary count picks up edits made inside the drawer.
  useEffect(() => {
    void fetchCount();
  }, [fetchCount]);

  useEffect(() => {
    if (!managerOpen) void fetchCount();
  }, [managerOpen, fetchCount]);

  const clearAll = async () => {
    try {
      const r = await fetch(buildListUrl());
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const rows = (await r.json()) as { id: number }[];
      await Promise.all(
        rows.map((m) =>
          fetch(`${BACKEND_BASE}/api/memory/${m.id}`, { method: 'DELETE' }),
        ),
      );
      await fetchCount();
    } catch (e) {
      console.error('[MemorySection] clear-all failed:', e);
      showToast(`清空失败：${(e as Error).message}`);
    }
  };

  const countText = count === null ? '加载中…' : `当前记住 ${count} 条`;
  const clearDisabled = count === null || count === 0;

  return (
    <section
      className="mb-4 rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <h3
        className="text-sm font-medium mb-3"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        记忆
      </h3>
      <div
        className="flex items-center justify-between p-4 rounded-lg"
        style={{ background: 'color-mix(in srgb, var(--color-bg-surface) 40%, transparent)' }}
      >
        <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
          {countText}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onOpenManager}
            className="px-3 py-1.5 text-xs rounded-md transition"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            管理
          </button>
          <button
            type="button"
            onClick={() => setPendingClearAll(true)}
            disabled={clearDisabled}
            className="px-3 py-1.5 text-xs rounded-md bg-rose-600/80 text-white hover:bg-rose-500 transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            全部清空
          </button>
        </div>
      </div>

      {pendingClearAll && (
        <ConfirmModal
          text="确认清空全部记忆？此操作不可恢复。"
          onConfirm={async () => {
            setPendingClearAll(false);
            await clearAll();
          }}
          onCancel={() => setPendingClearAll(false)}
        />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// v3-A — UI 风格主题选择器
// ---------------------------------------------------------------------------

const THEME_OPTIONS: { key: ThemeKey; label: string }[] = [
  { key: 'morandi',    label: '莫兰迪奶油' },
  { key: 'dusk',       label: '暮色梦幻' },
  { key: 'glass',      label: '玻璃拟态' },
  { key: 'watercolor', label: '水彩二次元' },
  { key: 'aurora',     label: '深海极光' },
  { key: 'sakura',     label: '樱花夜' },
  { key: 'cyber',      label: '赛博和风' },
  { key: 'lavender',   label: '薰衣草雾' },
];

// 各主题的 (bg-base, accent) 预览取色，与 themes.css 中的值保持一致；
// 用纯字面量是为了让色块在切换前就能预览所有主题，无需依赖当前 data-theme。
const THEME_PREVIEW: Record<ThemeKey, { base: string; accent: string }> = {
  morandi:    { base: '#F5F1EA', accent: '#9E9082' },
  dusk:       { base: '#16102A', accent: '#6B5BAF' },
  glass:      { base: '#0F1820', accent: 'rgba(80,180,160,0.55)' },
  watercolor: { base: '#FEF6FA', accent: '#C0607A' },
  aurora:     { base: '#0D1117', accent: '#00D4AA' },
  sakura:     { base: '#140B26', accent: '#8B2252' },
  cyber:      { base: '#0A0A0A', accent: '#FF4545' },
  lavender:   { base: '#231D35', accent: '#5A4878' },
};

// ---------------------------------------------------------------------------
// Bugfix-4 (4.2) — SystemStatusSection: backend RAM/CPU/Whisper/网络监控
// ---------------------------------------------------------------------------

export function SystemStatusSection() {
  const [data, setData] = useState<import('../lib/observability').SystemResources | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const { fetchSystemResources } = await import('../lib/observability');
        const r = await fetchSystemResources();
        if (!cancelled) setData(r);
      } catch {/* ignore */}
    };
    void tick();
    if (!autoRefresh) return () => { cancelled = true; };
    const h = setInterval(tick, 3000);  // 3s 刷一次
    return () => { cancelled = true; clearInterval(h); };
  }, [autoRefresh]);

  if (!data) {
    return (
      <Section title="系统状态">
        <div className="text-xs"
          style={{ color: 'var(--color-text-secondary)' }}>
          加载中…
        </div>
      </Section>
    );
  }

  if (!data.has_psutil) {
    return (
      <Section title="系统状态">
        <div className="text-xs"
          style={{ color: 'var(--color-text-secondary)' }}>
          psutil 未安装,无法采集系统资源。
        </div>
      </Section>
    );
  }

  const rss = data.backend_rss_mb ?? 0;
  const totalRam = data.system_total_ram_mb ?? 0;
  const ramPct = totalRam > 0 ? (rss / totalRam) * 100 : 0;
  const cpu = data.backend_cpu_percent ?? 0;

  const bar = (pct: number, color: string) => (
    <div className="h-1.5 rounded-full overflow-hidden flex-1"
      style={{ background: 'var(--color-bg-elevated)' }}>
      <div className="h-full rounded-full transition-all"
        style={{ width: `${Math.min(100, pct).toFixed(1)}%`, background: color }} />
    </div>
  );

  return (
    <Section title="系统状态">
      <div className="space-y-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="w-28 shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}>Backend RAM</span>
          {bar(ramPct, 'var(--color-accent)')}
          <span className="font-mono shrink-0 text-right w-32"
            style={{ color: 'var(--color-text-primary)' }}>
            {rss.toFixed(0)} MB / {(totalRam / 1024).toFixed(1)} GB
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-28 shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}>Backend CPU</span>
          {bar(cpu, cpu > 50 ? 'rgb(245,158,11)' : 'var(--color-accent)')}
          <span className="font-mono shrink-0 text-right w-32"
            style={{ color: 'var(--color-text-primary)' }}>
            {cpu.toFixed(1)} %
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-28 shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}>Whisper 模型</span>
          <span className="font-mono"
            style={{ color: 'var(--color-text-primary)' }}>
            {data.whisper_size ?? '?'} {data.whisper_disk_mb ? `· ${data.whisper_disk_mb} MB` : ''}
            {' · '}
            <span style={{
              color: data.whisper_loaded
                ? 'var(--color-text-accent)' : 'var(--color-text-secondary)',
            }}>
              {data.whisper_loaded ? '已加载' : '未加载 (lazy)'}
            </span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-28 shrink-0"
            style={{ color: 'var(--color-text-secondary)' }}>系统总 RAM</span>
          {bar(data.system_ram_percent ?? 0, 'var(--color-text-secondary)')}
          <span className="font-mono shrink-0 text-right w-32"
            style={{ color: 'var(--color-text-primary)' }}>
            {(data.system_ram_percent ?? 0).toFixed(0)}% 使用
          </span>
        </div>
        {(data.net_recv_kbps !== null || data.net_sent_kbps !== null) && (
          <div className="flex items-center gap-3 pt-1"
            style={{ color: 'var(--color-text-secondary)' }}>
            <span>⬇ {(data.net_recv_kbps ?? 0).toFixed(1)} KB/s</span>
            <span>⬆ {(data.net_sent_kbps ?? 0).toFixed(1)} KB/s</span>
          </div>
        )}
        <Toggle
          label="3 秒自动刷新"
          value={autoRefresh}
          onChange={setAutoRefresh}
        />
      </div>
    </Section>
  );
}


// bugfix-2: 导出供 SettingsPanelV2 复用。
export function ThemeSection() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);

  return (
    <section
      className="mb-4 rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <h3
        className="text-sm font-medium mb-3"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        UI 风格
      </h3>
      <div className="grid grid-cols-4 gap-3">
        {THEME_OPTIONS.map(({ key, label }) => {
          const preview = THEME_PREVIEW[key];
          const active = key === theme;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTheme(key)}
              className="flex flex-col items-center gap-1.5 p-2 rounded-md transition"
              style={
                active
                  ? {
                      background: 'color-mix(in srgb, var(--color-accent) 15%, transparent)',
                    }
                  : undefined
              }
              title={label}
            >
              <div
                className="w-8 h-8 rounded-md transition"
                style={{
                  background: `linear-gradient(135deg, ${preview.base} 0%, ${preview.base} 50%, ${preview.accent} 50%, ${preview.accent} 100%)`,
                  border: active
                    ? '2px solid var(--color-accent)'
                    : '1px solid var(--color-border-subtle)',
                }}
              />
              <span
                className="text-[11px] leading-tight text-center"
                style={{
                  color: active ? 'var(--color-text-accent)' : 'var(--color-text-secondary)',
                }}
              >
                {label}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}


// ---------------------------------------------------------------------------
// Basic profile section (nickname + language)
// ---------------------------------------------------------------------------

interface ProfileResponse {
  user_id: string;
  user_name: string;
  nickname: string | null;
  language: string | null;
  profile_summary: string | null;
}

interface ProfileSectionProps {
  userId: string;
  showToast: (text: string) => void;
}

// bugfix-2.2: 导出供 SettingsPanelV2 复用(基础信息部分)。
export function ProfileSection({ userId, showToast }: ProfileSectionProps) {
  const [nickname, setNickname] = useState('');
  const [language, setLanguage] = useState('zh-CN');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile`,
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as ProfileResponse;
        if (cancelled) return;
        setNickname(data.nickname ?? '');
        setLanguage(data.language ?? 'zh-CN');
        setLoaded(true);
      } catch (e) {
        console.error('[ProfileSection] fetch failed:', e);
        showToast(`基础信息加载失败：${(e as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, showToast]);

  const persist = async (patch: { nickname?: string; language?: string }) => {
    try {
      const r = await fetch(
        `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        },
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch (e) {
      console.error('[ProfileSection] patch failed:', e);
      showToast(`保存失败：${(e as Error).message}`);
    }
  };

  const inputStyle: React.CSSProperties = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  };

  return (
    <Section title="基础信息">
      <div className="flex items-center justify-between py-2 gap-3">
        <span
          className="text-sm shrink-0"
          style={{ color: 'var(--color-text-primary)' }}
        >
          称呼
        </span>
        <input
          type="text"
          value={nickname}
          disabled={!loaded}
          onChange={(e) => setNickname(e.target.value)}
          onBlur={() => loaded && void persist({ nickname })}
          placeholder="例如：小明"
          className="flex-1 max-w-[60%] rounded-md px-2 py-1 text-sm focus:outline-none disabled:opacity-50"
          style={inputStyle}
        />
      </div>
      <div className="flex items-center justify-between py-2 gap-3">
        <span
          className="text-sm shrink-0"
          style={{ color: 'var(--color-text-primary)' }}
        >
          语言偏好
        </span>
        <select
          value={language}
          disabled={!loaded}
          onChange={(e) => {
            const v = e.target.value;
            setLanguage(v);
            if (loaded) void persist({ language: v });
          }}
          className="rounded-md px-2 py-1 text-sm focus:outline-none disabled:opacity-50"
          style={inputStyle}
        >
          <option value="zh-CN">中文（zh-CN）</option>
          <option value="en-US">English (en-US)</option>
          <option value="ja-JP">日本語 (ja-JP)</option>
        </select>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// bugfix-2.2: 把原 SettingsPanel render 里的内联 JSX 块抽出来作独立 export,
// 供 SettingsPanelV2 复用。每个 wrapper 自带 state hook / localStorage 兜底,
// 与原内联版本同语义,不动业务逻辑。
// ---------------------------------------------------------------------------

interface ShowToastProps {
  showToast: (text: string) => void;
}

/** 记忆 / 用户画像 / 联网搜索 / 深度思考 四 toggle —— 写后端 config.yaml。*/
export function MemoryTogglesSection({ showToast }: ShowToastProps) {
  const longTermEnabled = useAppStore((s) => s.longTermEnabled);
  const profileEnabled  = useAppStore((s) => s.profileEnabled);
  const enableSearch    = useAppStore((s) => s.enableSearch);
  const enableThinking  = useAppStore((s) => s.enableThinking);

  const remoteToggle = (
    field: 'longTermEnabled' | 'profileEnabled' | 'enableSearch' | 'enableThinking',
    keyPath: string,
    next: boolean,
    label: string,
  ) => {
    const setterMap = {
      longTermEnabled: useAppStore.getState().setLongTermEnabled,
      profileEnabled:  useAppStore.getState().setProfileEnabled,
      enableSearch:    useAppStore.getState().setEnableSearch,
      enableThinking:  useAppStore.getState().setEnableThinking,
    } as const;
    const setter = setterMap[field];
    // 走共享 toggleConfigField helper · 同款逻辑被 ChatInput 簇3 钮复用 ·
    // 两入口共享一份 set+persist+rollback 链路防漂(lib/toggleConfig.ts)。
    toggleConfigField(setter, keyPath, next, (e: unknown) => {
      console.error(`[MemoryToggles] ${keyPath} sync failed:`, e);
      showToast(`${label} 写入失败：${extractErrorMessage(e)}`);
    });
  };

  return (
    <Section title="记忆开关">
      <Toggle
        label="长期记忆"
        value={longTermEnabled}
        onChange={(next) => remoteToggle('longTermEnabled', 'memory.long_term_enabled', next, '长期记忆')}
      />
      <Toggle
        label="用户画像"
        value={profileEnabled}
        onChange={(next) => remoteToggle('profileEnabled', 'memory.profile_enabled', next, '用户画像')}
      />
      <Toggle
        label="联网搜索"
        value={enableSearch}
        onChange={(next) => remoteToggle('enableSearch', 'search.enable_search', next, '联网搜索')}
      />
      <Toggle
        label="深度思考(慢)"
        value={enableThinking}
        onChange={(next) => remoteToggle('enableThinking', 'thinking.enable_thinking', next, '深度思考')}
      />
    </Section>
  );
}

/** ASR / VAD section · INV-17 v3 (2026-05-28) silero MicVAD 接管。
 *
 * 改动:
 *   - "语音检测阈值"(0-100)→ "VAD 进入阈值"(silero positiveSpeechThreshold 0.1-0.9)
 *   - "静音超时"(0.5-3.0s)→ "静音退出等待"(silero redemptionMs 500-3000ms · 同语义)
 *   - 其他 silero 参数(negative / minSpeech / preSpeechPad)默 default · 不暴露
 *   - 录音模式 / 静音麦克风 toggle 不动
 *
 * ⚠️ 注:silero 阈值改动需 destroy+new MicVAD 实例 · 本期 ship 不支持热更 ·
 *    用户调完 slider 后需重启 frontend 才生效(slider 仅写 store + localStorage)。
 */
export function AsrVadSection() {
  const recordingMode      = useAppStore((s) => s.recordingMode);
  const setRecordingMode   = useAppStore((s) => s.setRecordingMode);
  const vadPositive        = useAppStore((s) => s.vadPositiveThreshold);
  const setVadPositive     = useAppStore((s) => s.setVadPositiveThreshold);
  const vadRedemption      = useAppStore((s) => s.vadRedemptionMs);
  const setVadRedemption   = useAppStore((s) => s.setVadRedemptionMs);
  const muteWhileSpeaking  = useAppStore((s) => s.muteWhileSpeaking);
  const setMuteWhileSpeaking = useAppStore((s) => s.setMuteWhileSpeaking);
  const vadReady           = useAppStore((s) => s.vadReady);

  // 2026-06-05 · 删 mount[] useEffect hydrate + UI 层 LS 双写:
  // store init 已直读 LS,setter 已直写 LS(单源)。原"mount 才同步"导致 store
  // ≠ LS 长期 desync,且打开能力浮层会把 LS 旧 'vad' 灌进当前 session 翻转模式。
  const onRecordingMode = setRecordingMode;
  const onVadPositive = (v: number) => setVadPositive(Math.round(v * 100) / 100);
  const onVadRedemptionMs = (v: number) => setVadRedemption(Math.round(v));
  const onMuteWhileSpeaking = setMuteWhileSpeaking;

  return (
    <Section title="ASR / VAD">
      <Segmented<'manual' | 'vad'>
        label="录音模式"
        value={recordingMode}
        options={[
          { value: 'manual', label: '手动' },
          { value: 'vad', label: 'VAD' + (vadReady ? '' : ' (未就绪)') },
        ]}
        onChange={onRecordingMode}
      />
      <Slider
        label="VAD 进入阈值 (positive)"
        value={vadPositive}
        min={0.1} max={0.9} step={0.05}
        display={vadPositive.toFixed(2)}
        onChange={onVadPositive}
      />
      <Slider
        label="静音退出等待 (redemption)"
        value={vadRedemption}
        min={500} max={3000} step={100}
        display={`${(vadRedemption / 1000).toFixed(1)} s`}
        onChange={onVadRedemptionMs}
      />
      <div
        className="text-[10px] -mt-1 mb-1"
        style={{ color: 'var(--color-text-secondary)', opacity: 0.7 }}
      >
        阈值改动需重启前端生效 · silero MicVAD 实例需 destroy+new 重建
      </div>
      <Toggle
        label="Momo 说话时静音麦克风"
        value={muteWhileSpeaking}
        onChange={onMuteWhileSpeaking}
      />
    </Section>
  );
}

/** TTS 启用开关。*/
export function TtsSection({ showToast }: ShowToastProps) {
  const ttsEnabled = useAppStore((s) => s.ttsEnabled);
  const setTtsEnabled = useAppStore((s) => s.setTtsEnabled);

  const onToggle = (next: boolean) => {
    const prev = ttsEnabled;
    setTtsEnabled(next);
    setConfigField('tts.enabled', next).catch((e: unknown) => {
      console.error('[TtsSection] tts.enabled sync failed:', e);
      setTtsEnabled(prev);
      showToast(`启用 TTS 写入失败：${extractErrorMessage(e)}`);
    });
  };

  return (
    <Section title="TTS">
      <Toggle label="启用 TTS" value={ttsEnabled} onChange={onToggle} />
    </Section>
  );
}

/** 启动入场视频开关 —— 纯 localStorage(不走后端 config),重启生效。*/
export function SplashSection() {
  const [splashEnabled, setSplashEnabled] = useState<boolean>(true);

  useEffect(() => {
    try {
      const se = localStorage.getItem(LS_SPLASH_ENABLED);
      if (se === 'true' || se === 'false') setSplashEnabled(se === 'true');
    } catch {/* ignore */}
  }, []);

  const onChange = (v: boolean) => {
    setSplashEnabled(v);
    try { localStorage.setItem(LS_SPLASH_ENABLED, String(v)); } catch {/* ignore */}
  };

  return (
    <Section title="启动">
      <Toggle label="启动播放入场视频" value={splashEnabled} onChange={onChange} />
      <div
        className="text-xs py-1.5"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        把 intro.mp4 放进 frontend/public/splash/ 目录，启动时自动播放（点击 / 按键跳过）。
        文件不存在则 silent skip。
      </div>
    </Section>
  );
}


import { useCallback, useEffect, useState } from 'react';
import { useAppStore, type ThemeKey } from '../store';
import { setConfigField } from '../lib/window';
import { fetchModels, setModel, type ModelInfo } from '../lib/models';
import {
  triggerTestBriefing,
  resetCharacterState,
  fetchClipboardEnabled,
  setClipboardEnabled,
  type ClipboardItem,
} from '../lib/integrations';
import CapabilityPanel from './CapabilityPanel';
import MemoryManagerDrawer from './MemoryManagerDrawer';

const BACKEND_BASE = 'http://127.0.0.1:8000';

const LS_RECORDING_MODE   = 'momoos.recordingMode';
const LS_VAD_THRESHOLD    = 'momoos.vadThreshold';
const LS_SILENCE_TIMEOUT  = 'momoos.silenceTimeoutMs';   // stored in seconds
const LS_MUTE_SPEAKING    = 'momoos.muteWhileSpeaking';

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

function ProactiveSection({ showToast }: ProactiveSectionProps) {
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
      setConfigField(keyPath, value).catch((e) => {
        console.error(`[Proactive] ${keyPath} sync failed:`, e);
        rollback();
        showToast(`${label} 写入失败：${(e as Error).message}`);
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
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>叫醒 Cron</span>
              <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {wakeCallCron === '0 8 * * *' ? '每天 8:00' : '自定义'}
              </span>
            </div>
            <input
              type="text" value={wakeCronDraft} placeholder="0 8 * * *"
              onChange={(e) => setWakeCronDraft(e.target.value)}
              onBlur={() => commitTextField(
                wakeCronDraft, wakeCallCron, setWakeCallCron, setWakeCronDraft,
                'proactive.wake_call_briefing.cron', '叫醒 Cron',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className={inputCls} style={inputStyle}
            />
          </div>
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                城市（stage 2 天气查询）
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
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                Pending TTL（分钟）
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
                'proactive.wake_call_briefing.pending_ttl_minutes', 'Pending TTL',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className={inputCls} style={inputStyle}
            />
          </div>
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                Snooze 默认（分钟）
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
                'proactive.wake_call_briefing.default_snooze_minutes', 'Snooze 默认',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className={inputCls} style={inputStyle}
            />
          </div>
        </>
      )}

      {proactiveMode === 'morning_briefing' && (
        <>
          <div className="py-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>简报 Cron</span>
              <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {morningBriefingCron === '0 9 * * *' ? '每天 9:00' : '自定义'}
              </span>
            </div>
            <input
              type="text" value={morningCronDraft} placeholder="0 9 * * *"
              onChange={(e) => setMorningCronDraft(e.target.value)}
              onBlur={() => commitTextField(
                morningCronDraft, morningBriefingCron,
                setMorningBriefingCron, setMorningCronDraft,
                'proactive.morning_briefing.cron', '简报 Cron',
              )}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              className={inputCls} style={inputStyle}
            />
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

function ClipboardSection({ showToast }: ClipboardSectionProps) {
  const [enabled, setEnabled] = useState(true);
  const [items, setItems] = useState<ClipboardItem[]>([]);
  const [loading, setLoading] = useState(false);

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

      <div className="py-2">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            最近 {items.length} 条
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={fetchItems}
              disabled={loading}
              className="text-xs px-2 py-1 rounded"
              style={{
                background: 'var(--color-bg-input)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
                opacity: loading ? 0.5 : 1,
              }}
            >
              {loading ? '…' : '↻ 刷新'}
            </button>
            <button
              type="button"
              onClick={onClearAll}
              className="text-xs px-2 py-1 rounded"
              style={{
                background: 'var(--color-bg-input)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            >
              全部清除
            </button>
          </div>
        </div>
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
    </Section>
  );
}


// ---------------------------------------------------------------------------
// v3-G chunk 3b — 角色状态 section
// ---------------------------------------------------------------------------

interface CharacterStateSectionProps {
  showToast: (text: string) => void;
}

function CharacterStateSection({ showToast }: CharacterStateSectionProps) {
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

function MemorySection({
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

function ThemeSection() {
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
// v3-G chunk 1.7 — AI 模型切换器
// ---------------------------------------------------------------------------

interface ModelSectionProps {
  showToast: (text: string) => void;
}

function ModelSection({ showToast }: ModelSectionProps) {
  const [current, setCurrent] = useState<string>('');
  const [available, setAvailable] = useState<ModelInfo[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const state = await fetchModels();
        if (cancelled) return;
        setCurrent(state.current);
        setAvailable(state.available);
        setLoaded(true);
      } catch (e) {
        console.error('[ModelSection] fetch failed:', e);
        showToast(`AI 模型列表加载失败：${(e as Error).message}`);
      }
    })();
    return () => { cancelled = true; };
  }, [showToast]);

  const onChange = useCallback(async (next: string) => {
    if (next === current || busy) return;
    const prev = current;
    setCurrent(next);   // optimistic
    setBusy(true);
    try {
      const state = await setModel(next);
      setCurrent(state.current);
      const picked = state.available.find((m) => m.id === state.current);
      showToast(`已切换至 ${picked?.display_name ?? state.current}`);
    } catch (e) {
      console.error('[ModelSection] set failed:', e);
      setCurrent(prev);
      showToast(`切换失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }, [current, busy, showToast]);

  const currentInfo = available.find((m) => m.id === current);

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
        AI 模型
      </h3>

      {!loaded ? (
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          加载中…
        </div>
      ) : available.length === 0 ? (
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          config.yaml 没配置 available_models。
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {available.map((m) => {
              const active = m.id === current;
              const isPreview = m.tier === 'preview';
              return (
                <button
                  key={m.id}
                  type="button"
                  disabled={busy}
                  onClick={() => onChange(m.id)}
                  className="text-left p-3 rounded-md transition"
                  style={{
                    background: active
                      ? 'color-mix(in srgb, var(--color-accent) 15%, transparent)'
                      : 'var(--color-bg-elevated)',
                    border: active
                      ? '1.5px solid var(--color-accent)'
                      : '1px solid var(--color-border-subtle)',
                    cursor: busy ? 'wait' : 'pointer',
                    opacity: busy && !active ? 0.6 : 1,
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="text-sm font-medium"
                      style={{
                        color: active
                          ? 'var(--color-text-accent)'
                          : 'var(--color-text-primary)',
                      }}
                    >
                      {active ? '✓ ' : ''}{m.display_name}
                    </span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded"
                      style={
                        isPreview
                          ? {
                              background: 'rgba(245, 158, 11, 0.15)',
                              color: 'rgb(245, 158, 11)',
                              border: '1px solid rgba(245, 158, 11, 0.4)',
                            }
                          : {
                              background: 'var(--color-bg-elevated)',
                              color: 'var(--color-text-secondary)',
                              border: '1px solid var(--color-border-subtle)',
                            }
                      }
                    >
                      {m.tier}
                    </span>
                  </div>
                  <div
                    className="text-xs mt-1"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    {m.description}
                  </div>
                </button>
              );
            })}
          </div>
          <div
            className="text-[11px] mt-3"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            下次对话立即生效，无需重启。当前：
            <span style={{ color: 'var(--color-text-primary)' }}>
              {' '}{currentInfo?.display_name ?? current}
            </span>
          </div>
        </>
      )}
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

function ProfileSection({ userId, showToast }: ProfileSectionProps) {
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
// SettingsPanel
// ---------------------------------------------------------------------------

export default function SettingsPanel() {
  const longTermEnabled    = useAppStore((s) => s.longTermEnabled);
  const profileEnabled     = useAppStore((s) => s.profileEnabled);
  const enableSearch       = useAppStore((s) => s.enableSearch);
  const ttsEnabled         = useAppStore((s) => s.ttsEnabled);
  const defaultUserId      = useAppStore((s) => s.defaultUserId);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);

  const recordingMode      = useAppStore((s) => s.recordingMode);
  const setRecordingMode   = useAppStore((s) => s.setRecordingMode);
  const vadThreshold       = useAppStore((s) => s.vadThreshold);
  const setVadThreshold    = useAppStore((s) => s.setVadThreshold);
  const silenceTimeoutMs   = useAppStore((s) => s.silenceTimeoutMs);
  const setSilenceTimeoutMs = useAppStore((s) => s.setSilenceTimeoutMs);
  const muteWhileSpeaking  = useAppStore((s) => s.muteWhileSpeaking);
  const setMuteWhileSpeaking = useAppStore((s) => s.setMuteWhileSpeaking);

  const [toasts, setToasts] = useState<ToastInfo[]>([]);
  const showToast = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3000);
  }, []);

  const [memoryManagerOpen, setMemoryManagerOpen] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);

  // Hydrate ASR/VAD prefs from localStorage on mount
  useEffect(() => {
    try {
      const rm = localStorage.getItem(LS_RECORDING_MODE);
      if (rm === 'manual' || rm === 'vad') useAppStore.getState().setRecordingMode(rm);

      const vt = localStorage.getItem(LS_VAD_THRESHOLD);
      if (vt !== null) {
        const n = parseFloat(vt);
        if (!isNaN(n) && n >= 1 && n <= 100) useAppStore.getState().setVadThreshold(n);
      }

      const st = localStorage.getItem(LS_SILENCE_TIMEOUT);
      if (st !== null) {
        const sec = parseFloat(st);
        if (!isNaN(sec) && sec >= 0.5 && sec <= 3.0) {
          useAppStore.getState().setSilenceTimeoutMs(Math.round(sec * 1000));
        }
      }

      const ms = localStorage.getItem(LS_MUTE_SPEAKING);
      if (ms === 'true' || ms === 'false') {
        useAppStore.getState().setMuteWhileSpeaking(ms === 'true');
      }
    } catch (e) {
      console.warn('[SettingsPanel] localStorage hydrate failed:', e);
    }
  }, []);

  const remoteToggle = (
    field: 'longTermEnabled' | 'profileEnabled' | 'enableSearch' | 'ttsEnabled',
    keyPath: string,
    next: boolean,
    label: string,
  ) => {
    const setterMap: Record<typeof field, (v: boolean) => void> = {
      longTermEnabled: useAppStore.getState().setLongTermEnabled,
      profileEnabled:  useAppStore.getState().setProfileEnabled,
      enableSearch:    useAppStore.getState().setEnableSearch,
      ttsEnabled:      useAppStore.getState().setTtsEnabled,
    };
    const setter = setterMap[field];
    setter(next);
    setConfigField(keyPath, next).catch((e) => {
      console.error(`[SettingsPanel] ${keyPath} sync failed:`, e);
      setter(!next);
      showToast(`${label} 写入失败：${(e as Error).message}`);
    });
  };

  const onRecordingMode = (v: 'manual' | 'vad') => {
    setRecordingMode(v);
    try {
      localStorage.setItem(LS_RECORDING_MODE, v);
    } catch (e) {
      console.warn('[SettingsPanel] localStorage write failed:', e);
    }
  };

  const onVadThreshold = (v: number) => {
    const n = Math.round(v);
    setVadThreshold(n);
    try { localStorage.setItem(LS_VAD_THRESHOLD, String(n)); } catch {/* ignore */}
  };

  const onSilenceSeconds = (sec: number) => {
    const ms = Math.round(sec * 1000);
    setSilenceTimeoutMs(ms);
    try { localStorage.setItem(LS_SILENCE_TIMEOUT, sec.toFixed(1)); } catch {/* ignore */}
  };

  const onMuteWhileSpeaking = (v: boolean) => {
    setMuteWhileSpeaking(v);
    try { localStorage.setItem(LS_MUTE_SPEAKING, String(v)); } catch {/* ignore */}
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 relative">
      {/* v3-A — UI 风格选择，置顶 */}
      <ThemeSection />

      {/* v3-G chunk 1.7 — AI 模型切换（在 capability panel 之上，让用户先
          决定脑子用谁，再看 capability 列表）*/}
      <ModelSection showToast={showToast} />

      {/* v3-G chunk 0 — 能力总览（spec 称"tab"，但 SettingsPanel 是单列
          Section 布局，无 tab 容器；放成顶部 Section 是与现有 UX 最一致
          的近似，详见 chunk 0 报告偏离决定）*/}
      <div className="mb-4">
        <CapabilityPanel />
      </div>

      <Section title="Memory">
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
      </Section>

      <ProactiveSection showToast={showToast} />

      <ClipboardSection showToast={showToast} />

      <CharacterStateSection showToast={showToast} />

      <Section title="ASR / VAD">
        <Segmented<'manual' | 'vad'>
          label="录音模式"
          value={recordingMode}
          options={[
            { value: 'manual', label: '手动' },
            { value: 'vad', label: 'VAD' },
          ]}
          onChange={onRecordingMode}
        />
        <Slider
          label="语音检测阈值"
          value={vadThreshold}
          min={1}
          max={100}
          step={1}
          display={String(vadThreshold)}
          onChange={onVadThreshold}
        />
        <Slider
          label="静音超时"
          value={silenceTimeoutMs / 1000}
          min={0.5}
          max={3.0}
          step={0.1}
          display={`${(silenceTimeoutMs / 1000).toFixed(1)} s`}
          onChange={onSilenceSeconds}
        />
        <Toggle
          label="Momo 说话时静音麦克风"
          value={muteWhileSpeaking}
          onChange={onMuteWhileSpeaking}
        />
      </Section>

      <Section title="TTS">
        <Toggle
          label="启用 TTS"
          value={ttsEnabled}
          onChange={(next) => remoteToggle('ttsEnabled', 'tts.enabled', next, '启用 TTS')}
        />
      </Section>

      <MemorySection
        userId={defaultUserId}
        characterId={currentCharacterId}
        showToast={showToast}
        managerOpen={memoryManagerOpen}
        onOpenManager={() => setMemoryManagerOpen(true)}
        onCountChange={setMemoryCount}
        count={memoryCount}
      />

      <ProfileSection userId={defaultUserId} showToast={showToast} />

      <MemoryManagerDrawer
        open={memoryManagerOpen}
        userId={defaultUserId}
        characterId={currentCharacterId}
        onClose={() => setMemoryManagerOpen(false)}
        onCountChange={setMemoryCount}
      />

      {/* Toasts */}
      <div className="fixed bottom-4 right-4 z-40 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="text-sm px-3 py-2 rounded shadow-lg"
            style={{
              background: 'color-mix(in srgb, var(--color-bg-surface) 90%, transparent)',
              border: '1px solid rgba(244, 63, 94, 0.6)',
              color: 'var(--color-text-primary)',
            }}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

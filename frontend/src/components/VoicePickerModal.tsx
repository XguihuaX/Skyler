/**
 * Bugfix-3.3.1 — VoicePickerModal
 *
 * 角色 TTS voice 选择 modal:
 * - 列出系统 voice (从 /api/tts/voices 拉) + 用户复刻 voice
 *   (从 /api/tts/voices/cloned 拉)
 * - 每行 [试听] 按钮 (POST /api/tts/voice/preview, 播放 base64 wav)
 * - 单选 radio 让用户选; [保存] 时把 cosyvoice + voiceId 包成 voice_model JSON
 *   回给父组件 (父组件负责 PATCH /api/characters/:id)
 *
 * 复用:CharacterPanel.tsx 的 [📢 试听并选 voice] 按钮 + TTS tab gallery 视图
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Play, Pause, RefreshCw, X, CheckCircle2 } from 'lucide-react';

const _BACKEND_BASE = 'http://127.0.0.1:8000';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SystemVoiceInfo {
  id: string;
  label: string;
  traits: string;
  instruct: boolean | null;
}

export interface ClonedVoiceInfo {
  voice_id: string;
  create_time: string | null;
  update_time: string | null;
  status: string | null;
}

interface ClonedVoicesResp {
  voices: ClonedVoiceInfo[];
  cached: boolean;
}

interface TtsVoicesResp {
  providers: Array<{
    id: string;
    label: string;
    voices: SystemVoiceInfo[];
  }>;
}

interface UsageResp {
  by_voice: Array<{
    voice: string;
    characters: Array<{ id: number; name: string }>;
  }>;
}

interface VoicePickerModalProps {
  /** Currently selected voice id (so we radio-select on open). */
  currentVoice: string | null;
  /** Optional: a character name shown in the title, eg "八重神子". */
  characterName?: string;
  onClose: () => void;
  /**
   * 用户 [保存] 时回调。父组件 build voice_model JSON + PATCH。
   * isCloned 让父组件按需写 instruct_supported (复刻 voice 一律 true)。
   */
  onSave: (params: { voiceId: string; isCloned: boolean; instructSupported: boolean }) => void;
  showToast: (text: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function VoicePickerModal({
  currentVoice,
  characterName,
  onClose,
  onSave,
  showToast,
}: VoicePickerModalProps) {
  const [systemVoices, setSystemVoices] = useState<SystemVoiceInfo[]>([]);
  const [clonedVoices, setClonedVoices] = useState<ClonedVoiceInfo[]>([]);
  const [usageByVoice, setUsageByVoice] = useState<Record<string, Array<{ id: number; name: string }>>>({});
  const [selectedId, setSelectedId] = useState<string>(currentVoice ?? '');
  const [loadingSys, setLoadingSys] = useState(false);
  const [loadingCloned, setLoadingCloned] = useState(false);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const refreshSystem = useCallback(async () => {
    setLoadingSys(true);
    try {
      const r = await fetch(`${_BACKEND_BASE}/api/tts/voices`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as TtsVoicesResp;
      // 只关心 cosyvoice (本 stage 不支持给 character 切 Edge/SoVITS provider)
      const cosy = j.providers.find((p) => p.id === 'cosyvoice');
      setSystemVoices(cosy?.voices ?? []);
    } catch (e) {
      showToast(`系统 voice 加载失败:${(e as Error).message}`);
    } finally {
      setLoadingSys(false);
    }
  }, [showToast]);

  const refreshCloned = useCallback(async (force = false) => {
    setLoadingCloned(true);
    try {
      const url = `${_BACKEND_BASE}/api/tts/voices/cloned${force ? '?force=1' : ''}`;
      const r = await fetch(url);
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (j?.detail) detail = String(j.detail);
        } catch { /* ignore */ }
        throw new Error(detail);
      }
      const j = (await r.json()) as ClonedVoicesResp;
      setClonedVoices(j.voices);
    } catch (e) {
      showToast(`复刻 voice 加载失败:${(e as Error).message}`);
    } finally {
      setLoadingCloned(false);
    }
  }, [showToast]);

  const refreshUsage = useCallback(async () => {
    try {
      const r = await fetch(`${_BACKEND_BASE}/api/tts/voices/usage`);
      if (!r.ok) return;
      const j = (await r.json()) as UsageResp;
      const map: Record<string, Array<{ id: number; name: string }>> = {};
      for (const e of j.by_voice) map[e.voice] = e.characters;
      setUsageByVoice(map);
    } catch {/* ignore */}
  }, []);

  useEffect(() => {
    void refreshSystem();
    void refreshCloned();
    void refreshUsage();
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, [refreshSystem, refreshCloned, refreshUsage]);

  const onPreview = useCallback(async (voiceId: string) => {
    // 已在播这个 voice → 暂停
    if (previewingId === voiceId && audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
      setPreviewingId(null);
      return;
    }
    // 在播别的 voice → 切到新的
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setPreviewingId(voiceId);
    try {
      const r = await fetch(`${_BACKEND_BASE}/api/tts/voice/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice: voiceId }),
      });
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (j?.detail) detail = String(j.detail);
        } catch { /* ignore */ }
        throw new Error(detail);
      }
      const j = (await r.json()) as { audio_b64: string };
      const a = new Audio(`data:audio/wav;base64,${j.audio_b64}`);
      audioRef.current = a;
      a.onended = () => {
        if (audioRef.current === a) {
          audioRef.current = null;
          setPreviewingId((cur) => (cur === voiceId ? null : cur));
        }
      };
      await a.play();
    } catch (e) {
      showToast(`试听失败:${(e as Error).message}`);
      setPreviewingId(null);
    }
  }, [previewingId, showToast]);

  const onSubmit = useCallback(() => {
    if (!selectedId) {
      showToast('请先选择一个 voice');
      return;
    }
    const isCloned = clonedVoices.some((v) => v.voice_id === selectedId);
    const sysHit = systemVoices.find((v) => v.id === selectedId);
    // 复刻 voice 在 DashScope 控制台一律允许 instruct (用户拍板);
    // 系统 voice 看 yaml::tts.available_voices[*].instruct 字段。
    const instructSupported = isCloned ? true : (sysHit?.instruct === true);
    onSave({ voiceId: selectedId, isCloned, instructSupported });
  }, [selectedId, clonedVoices, systemVoices, onSave, showToast]);

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[560px] max-h-[90vh] overflow-y-auto shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <h4 className="text-sm font-semibold"
              style={{ color: 'var(--color-text-primary)' }}>
              选择 voice{characterName ? ` — ${characterName}` : ''}
            </h4>
            <p className="text-xs mt-0.5"
              style={{ color: 'var(--color-text-secondary)' }}>
              系统音色 + 你在 DashScope 控制台复刻的 voice。点 ▶ 试听,radio 选定后[保存]生效。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded transition"
            style={{ color: 'var(--color-text-secondary)' }}
            title="关闭"
          >
            <X size={16} />
          </button>
        </div>

        {/* 系统 voice */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <h5 className="text-xs font-medium uppercase tracking-wide"
              style={{ color: 'var(--color-text-secondary)' }}>
              系统音色 {loadingSys ? '(加载中…)' : `(${systemVoices.length})`}
            </h5>
          </div>
          <ul className="space-y-1.5">
            {systemVoices.map((v) => (
              <VoiceRow
                key={v.id}
                voiceId={v.id}
                label={v.label}
                sub={v.traits + (v.instruct ? ' · 支持情感' : '')}
                kindLabel="系统"
                selected={selectedId === v.id}
                playing={previewingId === v.id}
                usage={usageByVoice[v.id]}
                onSelect={() => setSelectedId(v.id)}
                onPreview={() => void onPreview(v.id)}
              />
            ))}
          </ul>
        </div>

        {/* 用户复刻 voice */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <h5 className="text-xs font-medium uppercase tracking-wide"
              style={{ color: 'var(--color-text-secondary)' }}>
              用户复刻 {loadingCloned ? '(加载中…)' : `(${clonedVoices.length})`}
            </h5>
            <button
              type="button"
              onClick={() => void refreshCloned(true)}
              disabled={loadingCloned}
              className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
              style={{ color: 'var(--color-text-secondary)' }}
              title="强制重拉 DashScope 复刻列表(跳过 5min 缓存)"
            >
              <RefreshCw size={10} className={loadingCloned ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>
          {clonedVoices.length === 0 && !loadingCloned && (
            <div className="text-xs italic px-2 py-2"
              style={{ color: 'var(--color-text-secondary)' }}>
              没有复刻 voice。在 DashScope 控制台
              (model-studio.console.aliyun.com) 复刻后,这里按 [刷新]。
            </div>
          )}
          <ul className="space-y-1.5">
            {clonedVoices.map((v) => (
              <VoiceRow
                key={v.voice_id}
                voiceId={v.voice_id}
                label={v.voice_id.replace(/^cosyvoice-v\d[.\d]*-plus-bailian-/, '*')
                  .slice(0, 22) + '…'}
                sub={`复刻 · ${v.status ?? '?'} · ${v.update_time ?? v.create_time ?? ''}`}
                kindLabel="复刻"
                selected={selectedId === v.voice_id}
                playing={previewingId === v.voice_id}
                usage={usageByVoice[v.voice_id]}
                onSelect={() => setSelectedId(v.voice_id)}
                onPreview={() => void onPreview(v.voice_id)}
              />
            ))}
          </ul>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
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
            onClick={onSubmit}
            disabled={!selectedId}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Row component
// ---------------------------------------------------------------------------

interface VoiceRowProps {
  voiceId: string;
  label: string;
  sub: string;
  kindLabel: string;
  selected: boolean;
  playing: boolean;
  usage?: Array<{ id: number; name: string }>;
  onSelect: () => void;
  onPreview: () => void;
}

function VoiceRow({
  voiceId, label, sub, kindLabel, selected, playing, usage, onSelect, onPreview,
}: VoiceRowProps) {
  return (
    <li
      className="rounded-md px-3 py-2 flex items-center gap-3"
      style={{
        background: selected
          ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
          : 'var(--color-bg-input)',
        border: selected
          ? '1px solid var(--color-accent)'
          : '1px solid var(--color-border-subtle)',
      }}
    >
      <input
        type="radio"
        checked={selected}
        onChange={onSelect}
        className="shrink-0 cursor-pointer"
        style={{ accentColor: 'var(--color-accent)' }}
        aria-label={`选 ${label}`}
      />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm truncate"
            style={{ color: 'var(--color-text-primary)' }}>
            {label}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-secondary)',
            }}>
            {kindLabel}
          </span>
          {selected && (
            <CheckCircle2 size={12} style={{ color: 'var(--color-text-accent)' }} />
          )}
        </div>
        <div className="text-[11px] truncate"
          style={{ color: 'var(--color-text-secondary)' }}>
          {sub}
        </div>
        {usage && usage.length > 0 && (
          <div className="text-[10px] mt-0.5 truncate"
            style={{ color: 'var(--color-text-accent)' }}>
            已用于角色:{usage.map((c) => c.name).join(', ')}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onPreview}
        className="p-1.5 rounded transition shrink-0"
        style={{ color: 'var(--color-text-accent)' }}
        title={playing ? '暂停' : '试听'}
        aria-label={playing ? '暂停' : '试听'}
      >
        {playing ? <Pause size={14} /> : <Play size={14} />}
      </button>

      <span className="text-[10px] font-mono shrink-0 hidden md:inline"
        style={{ color: 'var(--color-text-secondary)' }}>
        {voiceId.length > 22 ? `${voiceId.slice(0, 20)}…` : voiceId}
      </span>
    </li>
  );
}

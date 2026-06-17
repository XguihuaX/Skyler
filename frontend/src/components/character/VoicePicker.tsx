/**
 * INV-11 Stage 1.5 paradigm B (2026-05-26) — VoicePicker (inline)
 *
 * 取代原 VoicePickerModal · 一屏 inline 显示 provider × model × voice 3 级
 * dropdown + voice list 预览(仅 cosyvoice)+ TTS 语言 + 非 cosyvoice emotion
 * 提示框。任意 dropdown change 自动 debounce 300ms PATCH
 * /api/characters/{cid} (edit 模式;create 模式仅更新 form 等用户点 [保存])。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  Pause,
  Play,
  RefreshCw,
} from 'lucide-react';
import { fetchVoiceAliases, resolveVoiceName } from '../../lib/voiceAliases';
import { patchCharacter } from '../../lib/config';

const _BACKEND_BASE = 'http://127.0.0.1:8000';

// ---------------------------------------------------------------------------
// Types (mirror backend/tts/registry.py::get_provider_tree)
// ---------------------------------------------------------------------------

interface ProvidersTreeVoice {
  id: string;
  label: string;
  traits?: string;
  instruct?: boolean | null;
  cloned?: boolean;
  bound_character_id?: number;
  bound_character_name?: string;
  requires_reference_upload?: boolean;
  uses_emotion_bank?: boolean;
}

interface ProvidersTreeModel {
  id: string;
  label: string;
  tts_language?: string;
  gpt_weights?: string;
  sovits_weights?: string;
  emotion_bank_dir?: string;
  remote_emotion_bank_dir?: string;
  default_emotion?: string;
  server_url?: string;
  inference_params?: Record<string, unknown>;
  fish_latency?: string;
  voices: ProvidersTreeVoice[];
}

interface ProvidersTreeResp {
  providers: Array<{ id: string; label: string; models: ProvidersTreeModel[] }>;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface VoicePickerProps {
  /** raw character.voice_model JSON string (form state in parent) */
  voiceModel: string;
  /** null = create 模式 / 未保存 character · 不发 PATCH · 仅更新 form */
  characterId: number | null;
  characterName?: string;
  /** parent form state setter — 让 [保存] 按钮也能 submit 同步 */
  onVoiceModelChange: (json: string) => void;
  showToast: (text: string) => void;
  inputStyle: React.CSSProperties;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface ParsedVm {
  provider: string;
  model: string;
  voice: string;
  tts_language?: 'zh' | 'ja' | 'en';
}

const _CLONED_PREFIX = 'cosyvoice-v3.5-plus-bailian-';

function _inferCosyModel(voiceId: string): string {
  return voiceId.startsWith(_CLONED_PREFIX)
    ? 'cosyvoice-v3.5-plus'
    : 'cosyvoice-v3-flash';
}

function _parseVm(
  raw: string,
  tree: ProvidersTreeResp | null,
): ParsedVm {
  let provider = 'cosyvoice';
  let model = '';
  let voice = '';
  let ttsLang: 'zh' | 'ja' | 'en' | undefined;
  try {
    const j = JSON.parse(raw) as Record<string, unknown>;
    if (typeof j.provider === 'string') provider = j.provider;
    if (typeof j.model === 'string') model = j.model;
    if (typeof j.voice === 'string') voice = j.voice;
    const tl = j.tts_language;
    if (tl === 'zh' || tl === 'ja' || tl === 'en') ttsLang = tl;
  } catch { /* fallthrough · 空 / 旧格式 */ }

  // Infer model if missing (legacy cosyvoice slim schema)
  if (!model) {
    if (provider === 'cosyvoice') {
      model = _inferCosyModel(voice);
    } else if (tree) {
      model = tree.providers.find((p) => p.id === provider)?.models[0]?.id ?? '';
    }
  }
  return { provider, model, voice, tts_language: ttsLang };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function VoicePicker({
  voiceModel,
  characterId,
  characterName,
  onVoiceModelChange,
  showToast,
  inputStyle,
}: VoicePickerProps) {
  const [tree, setTree] = useState<ProvidersTreeResp | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [aliases, setAliases] = useState<Record<string, string>>({});
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshTree = useCallback(async () => {
    setTreeLoading(true);
    setTreeError(null);
    try {
      const r = await fetch(`${_BACKEND_BASE}/api/tts/providers`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as ProvidersTreeResp;
      setTree(j);
    } catch (e) {
      setTreeError((e as Error).message);
      showToast(`Provider registry 加载失败:${(e as Error).message}`);
    } finally {
      setTreeLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void refreshTree();
    void (async () => {
      try {
        const m = await fetchVoiceAliases();
        setAliases(m);
      } catch { /* ignore */ }
    })();
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [refreshTree]);

  const parsed = useMemo(() => _parseVm(voiceModel, tree), [voiceModel, tree]);
  const providerNode = tree?.providers.find((p) => p.id === parsed.provider);
  const modelNode = providerNode?.models.find((m) => m.id === parsed.model);
  const voicesOfModel = modelNode?.voices ?? [];

  // Build new voice_model JSON for a (provider, model, voice, ttsLang) tuple.
  // cosyvoice 必带 model 字段(否则 _parseVm 只能从 voice 前缀推断 · 系统音 ↔
  // plus model 切换会卡死回 flash · 见 2026-05-26 hotfix)。
  //
  // 2026-06-11 · PM SPEC-LOCK A-ii:gsv 分支改 thin reference,只写
  // {provider, model, voice?, tts_language?},不再 spread mNode 全字段。
  // gpt_weights / sovits_weights / emotion_bank_dir / remote_emotion_bank_dir /
  // default_emotion / inference_params 全走 backend tts_models_cache spec(per-model
  // 级 tier · 阶段 ① 已落)· server_url 走全局 ai_providers · 两者跟 thin reference
  // 正交。fish 分支保持原状(下次单列改造,本轮范围外)。
  const buildJsonFor = useCallback(
    (
      provider: string,
      model: string,
      voiceId: string,
      ttsLang?: 'zh' | 'ja' | 'en',
    ): string => {
      const pNode = tree?.providers.find((p) => p.id === provider);
      const mNode = pNode?.models.find((m) => m.id === model);
      const vNode = mNode?.voices.find((v) => v.id === voiceId);
      // 2026-06-15 SPEC:语种 = model 注册时声明的属性,不再 per-character
      // 写 voice_model.tts_language。backend resolver 三 tier 第二档从注册表
      // (provider, model) spec.tts_language 兜底,UI 永远不写 override。
      // 现有 voice_model 旧 override 值(如 cid=1 Momo 'ja')无害保留,
      // resolver 第一档继续读 · 跟从 spec 继承同结果。
      // ttsLang 参数保留(callsites 仍传 parsed.tts_language 以保 type 兼容)·
      // buildJsonFor 一律不写 vm.tts_language · 留给 spec 兜底。
      if (provider === 'cosyvoice') {
        const isCloned = vNode?.cloned === true;
        const instructSupported = isCloned ? true : vNode?.instruct === true;
        const vm: Record<string, unknown> = {
          provider,
          model,
          voice: voiceId,
          instruct_supported: instructSupported,
        };
        return JSON.stringify(vm);
      }
      if (provider === 'gsv') {
        // thin reference · 不 spread · backend 三 tier 自动从 tts_models_cache 解析
        const vm: Record<string, unknown> = { provider, model };
        if (voiceId && voiceId !== 'emotion_bank' && voiceId !== 'reference') {
          vm.voice = voiceId;
        }
        return JSON.stringify(vm);
      }
      // fish · 保持原 spread 行为(本轮范围外 · 由后续 thin 化单列处理)·
      // spread 会自动从 mNode 拿 tts_language(注册表 spec 'ja')写入 vm —
      // 但这只是 spread 副作用 · 跟 resolver 第一档读同结果,无害保留。
      if (!mNode) return voiceModel;
      const vm: Record<string, unknown> = { provider, model };
      for (const [k, v] of Object.entries(mNode)) {
        if (k === 'id' || k === 'label' || k === 'voices') continue;
        vm[k] = v;
      }
      if (voiceId && voiceId !== 'reference' && voiceId !== 'emotion_bank') {
        vm.voice = voiceId;
      }
      return JSON.stringify(vm);
    },
    [tree, voiceModel],
  );

  // propagate to form + debounce 300ms PATCH (edit mode only)
  const propagate = useCallback(
    (newJson: string) => {
      onVoiceModelChange(newJson);
      if (characterId === null) return;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        void (async () => {
          setSaving(true);
          try {
            await patchCharacter(characterId, { voice_model: newJson });
            showToast('✓ voice 已自动保存');
          } catch (e) {
            showToast(`voice 保存失败:${(e as Error).message}`);
          } finally {
            setSaving(false);
          }
        })();
      }, 300);
    },
    [characterId, onVoiceModelChange, showToast],
  );

  const onProviderChange = (newProvider: string) => {
    const p = tree?.providers.find((x) => x.id === newProvider);
    const firstModel = p?.models[0];
    const firstVoice = firstModel?.voices[0];
    if (!firstModel || !firstVoice) {
      showToast(`Provider ${newProvider} 暂无 model/voice`);
      return;
    }
    propagate(buildJsonFor(newProvider, firstModel.id, firstVoice.id));
  };

  const onModelChange = (newModel: string) => {
    const m = providerNode?.models.find((x) => x.id === newModel);
    const firstVoice = m?.voices[0];
    if (!m || !firstVoice) {
      showToast(`Model ${newModel} 暂无 voice`);
      return;
    }
    propagate(buildJsonFor(parsed.provider, newModel, firstVoice.id));
  };

  const onVoiceSelect = (newVoice: string) => {
    // 2026-06-15 SPEC:不再传 parsed.tts_language · UI 不写 override · 语种
    // 由 backend resolver 第二档从 model spec 兜底(同 onProviderChange /
    // onModelChange 也都不传 lang)。
    propagate(buildJsonFor(parsed.provider, parsed.model, newVoice));
  };

  // 2026-06-15 SPEC:onTtsLangChange 删除 · TTS 语言下拉已删 · 不再有调用点。

  const onPreview = useCallback(async (voiceId: string) => {
    if (previewingId === voiceId && audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
      setPreviewingId(null);
      return;
    }
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

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label
          className="block text-xs"
          style={{ color: 'var(--color-text-primary)' }}
        >
          TTS 声音{characterName ? ` — ${characterName}` : ''}
        </label>
        <div className="flex items-center gap-2">
          {saving && (
            <span
              className="text-[10px]"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              保存中…
            </span>
          )}
          <button
            type="button"
            onClick={() => void refreshTree()}
            disabled={treeLoading}
            className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
            style={{ color: 'var(--color-text-secondary)' }}
            title="刷新 provider registry"
          >
            <RefreshCw
              size={10}
              className={treeLoading ? 'animate-spin' : ''}
            />
            刷新
          </button>
        </div>
      </div>

      {/* Provider */}
      <div className="relative mb-1">
        <select
          value={parsed.provider}
          onChange={(e) => onProviderChange(e.target.value)}
          className="w-full appearance-none rounded-md px-2 py-1.5 pr-8 text-sm focus:outline-none"
          style={inputStyle}
        >
          {(tree?.providers ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
        <ChevronDown
          size={14}
          className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none"
          style={{ color: 'var(--color-text-secondary)' }}
        />
      </div>

      {/* Model */}
      <div className="relative mb-1">
        <select
          value={parsed.model}
          onChange={(e) => onModelChange(e.target.value)}
          className="w-full appearance-none rounded-md px-2 py-1.5 pr-8 text-sm focus:outline-none"
          style={inputStyle}
        >
          {(providerNode?.models ?? []).map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
        <ChevronDown
          size={14}
          className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none"
          style={{ color: 'var(--color-text-secondary)' }}
        />
      </div>

      {/* Voice list (cosyvoice only) · A2: 系统音 + 复刻双轨时分 section header,
          单类型不显示 header(避免单调 list 上方挂个空标题)。 */}
      {parsed.provider === 'cosyvoice' && (() => {
        const systemList = voicesOfModel.filter((v) => v.cloned !== true);
        const clonedList = voicesOfModel.filter((v) => v.cloned === true);
        const showHeaders = systemList.length > 0 && clonedList.length > 0;

        const renderRow = (v: ProvidersTreeVoice) => {
          const isCloned = v.cloned === true;
          const aliasName = isCloned ? resolveVoiceName(v.id, aliases) : v.label;
          const label = isCloned && v.bound_character_name
            ? `${aliasName} · 绑 ${v.bound_character_name}`
            : aliasName;
          const sub = isCloned
            ? (v.traits ?? '复刻')
            : (v.traits ?? '') + (v.instruct ? ' · 支持情感' : '');
          return (
            <VoiceRow
              key={v.id}
              voiceId={v.id}
              label={label}
              sub={sub}
              kindLabel={isCloned ? '复刻' : '系统'}
              selected={parsed.voice === v.id}
              playing={previewingId === v.id}
              onSelect={() => onVoiceSelect(v.id)}
              onPreview={() => void onPreview(v.id)}
            />
          );
        };

        return (
          <div className="mt-2">
            <div className="text-[10px] mb-1 uppercase tracking-wide"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              选音色 {treeLoading ? '(加载中…)' : `(${voicesOfModel.length})`}
            </div>
            {showHeaders ? (
              <>
                {systemList.length > 0 && (
                  <>
                    <SectionHeader>── 系统音色 ──</SectionHeader>
                    <ul className="space-y-1.5 mb-2">
                      {systemList.map(renderRow)}
                    </ul>
                  </>
                )}
                {clonedList.length > 0 && (
                  <>
                    <SectionHeader>── 用户复刻 ──</SectionHeader>
                    <ul className="space-y-1.5">
                      {clonedList.map(renderRow)}
                    </ul>
                  </>
                )}
              </>
            ) : (
              <ul className="space-y-1.5">
                {voicesOfModel.map(renderRow)}
              </ul>
            )}
          </div>
        );
      })()}

      {/* Non-cosyvoice provider hint */}
      {parsed.provider !== 'cosyvoice' && (
        <div
          className="mt-2 px-2 py-1.5 rounded text-[11px]"
          style={{
            background: 'color-mix(in srgb, var(--color-accent) 8%, transparent)',
            border: '1px solid var(--color-border-subtle)',
            color: 'var(--color-text-secondary)',
          }}
        >
          {parsed.provider === 'fish' && (
            <>⚠ Fish provider · reference audio 由 character 上传(INV-12 Stage 3 backlog)· 切换即用 model default 配置。</>
          )}
          {parsed.provider === 'gsv' && (
            <>⚠ GSV provider · 使用 emotion bank(16 ref / model · LLM emotion 输出自动路由)· 切换即用 model default 配置。</>
          )}
        </div>
      )}

      {treeError && (
        <p
          className="text-[10px] mt-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          Provider registry 加载失败:{treeError}
        </p>
      )}

      {/* TTS 语言:2026-06-15 SPEC · 改为只读 · 取自所选 model 的 spec
          tts_language(来自 /api/tts/providers tree · mNode.tts_language ·
          registry 已 expose)· 不再 per-character 可编辑下拉。
          语种 = model 注册时声明的属性,resolver 后端走"音色原生语种兜底"
          (override 档保留但 UI 不写,留作未来真·多语种音色用)。
          ja/en 角色的双语 directive 注入由后端按 tts_language 自动触发,
          不再需要用户手动选 ja 才启用。 */}
      {parsed.voice && modelNode && (
        <div className="mt-2 text-[11px]"
          style={{ color: 'var(--color-text-secondary)' }}>
          TTS 语言:
          <span className="ml-1 font-mono"
            style={{ color: 'var(--color-text-primary)' }}>
            {(() => {
              const lang = modelNode.tts_language;
              if (lang === 'ja') return '日语(中文字幕 + 日语朗读)';
              if (lang === 'en') return '英语(中文字幕 + 英文朗读)';
              if (lang === 'zh') return '中文';
              return lang ?? '中文';
            })()}
          </span>
          <span className="ml-1" style={{ color: 'var(--color-text-secondary)' }}>
            (来自 model)
          </span>
        </div>
      )}

      {characterId === null && (
        <p
          className="text-[10px] mt-2"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          ⓘ 新建角色:点 [保存] 后自动启用 voice 自动保存。
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[10px] mt-1 mb-1 font-medium tracking-wide"
      style={{ color: 'var(--color-text-secondary)' }}
    >
      {children}
    </div>
  );
}

interface VoiceRowProps {
  voiceId: string;
  label: string;
  sub: string;
  kindLabel: string;
  selected: boolean;
  playing: boolean;
  onSelect: () => void;
  onPreview: () => void;
}

function VoiceRow({
  voiceId, label, sub, kindLabel, selected, playing, onSelect, onPreview,
}: VoiceRowProps) {
  return (
    <li
      className="rounded-md px-2 py-1.5 flex items-center gap-2"
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
          <span
            className="text-xs truncate"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {label}
          </span>
          <span
            className="text-[10px] px-1 py-0.5 rounded shrink-0"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-secondary)',
            }}
          >
            {kindLabel}
          </span>
          {selected && (
            <CheckCircle2 size={10} style={{ color: 'var(--color-text-accent)' }} />
          )}
        </div>
        {sub && (
          <div
            className="text-[10px] truncate"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {sub}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={onPreview}
        className="p-1 rounded transition shrink-0"
        style={{ color: 'var(--color-text-accent)' }}
        title={playing ? '暂停' : '试听'}
        aria-label={playing ? '暂停' : '试听'}
      >
        {playing ? <Pause size={12} /> : <Play size={12} />}
      </button>
      <span
        className="text-[10px] font-mono shrink-0 hidden md:inline"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {voiceId.length > 18 ? `${voiceId.slice(0, 16)}…` : voiceId}
      </span>
    </li>
  );
}

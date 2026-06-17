import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Cloud,
  KeyRound,
  Mic,
  Pencil,
  Plus,
  Server,
  Trash2,
  Volume2,
  type LucideIcon,
} from 'lucide-react';
import { setConfigField } from '../../lib/window';
import { fetchVoiceAliases, setVoiceAlias, resolveVoiceName } from '../../lib/voiceAliases';
import {
  fetchTtsUsage, fetchRecentCalls, sourceLabel,
  type TtsUsage, type RecentCall, type UsageRange,
} from '../../lib/observability';
import {
  type AIProvider,
  type AIVendor,
  type GroupedProvidersResponse,
  type ProviderType,
  type VendorGroup,
  activateProvider,
  deleteProvider,
  deleteVendor,
  listProvidersByType,
  updateProvider,
} from '../../lib/ai_providers';
import {
  AsrVadSection,
  TtsSection,
} from '../SettingsPanelLegacy';
import AddModelModal from './AddModelModal';
import AddVendorModal from './AddVendorModal';
import AddGsvModelModal from './AddGsvModelModal';
import {
  type TtsModel,
  type EmotionCoverage,
  listTtsModels,
  deleteTtsModel,
  getGsvServerUrl,
  setGsvServerUrl,
  getEmotionCoverage,
} from '../../lib/tts_models';
import VendorCredentialsModal from './VendorCredentialsModal';

/**
 * bugfix-3.2: 📂 能力 → AI Providers section 主组件。
 *
 * 3 tab (LLM / ASR / TTS) — 每 tab 用 ``listProvidersByType`` 拉 grouped
 * shape, 渲染 vendor card + 嵌入 provider 行。builtin 不可删 (button hide),
 * custom 可删可编辑(本 stage 只做 delete, edit 留 polish)。
 *
 * Activate 流程:
 *   - vendor.has_credential=false → 弹 VendorCredentialsModal 引导先配凭证
 *     (用户配完关 modal 时 onSaved 触发 refresh,然后 caller 仍需手动 activate)
 *   - provider.enabled=false → toast "请先启用"
 *   - 都满足 → POST activate, 成功 toast, 刷新列表(active 高亮换位)
 *   - 失败(no_credential / not_enabled / 其他) → toast 后端 detail
 *
 * 切换 tab 不重新 fetchVendors 列表(vendor 不分 type),只重新 fetch providers。
 */

interface AIProvidersSectionProps {
  showToast: (text: string) => void;
}

const TABS: { id: ProviderType; label: string }[] = [
  { id: 'llm', label: 'LLM 模型' },
  { id: 'asr', label: 'ASR / 语音识别' },
  { id: 'tts', label: 'TTS / 语音合成' },
];

export default function AIProvidersSection({ showToast }: AIProvidersSectionProps) {
  const [tab, setTab] = useState<ProviderType>('llm');
  const [grouped, setGrouped] = useState<GroupedProvidersResponse | null>(null);
  const [loading, setLoading] = useState(false);

  // bugfix-3.2.8: "+ 添加 X 模型" 在某个 vendor card 内触发; 记目标 vendor。
  const [addModelForVendor, setAddModelForVendor] = useState<AIVendor | null>(null);
  // 独立"+ 添加自定义 Vendor"按钮触发。
  const [addVendorOpen, setAddVendorOpen] = useState(false);

  // 凭证 modal 状态:打开时记目标 vendor;关闭 reset null
  const [credentialsForVendor, setCredentialsForVendor] = useState<AIVendor | null>(null);

  // 删 vendor 确认 (二段:先 confirm 后 delete)
  const [pendingDeleteVendor, setPendingDeleteVendor] = useState<AIVendor | null>(null);
  // bugfix-3.2.8: 删 provider 二段确认 (代替原 confirm() 浏览器弹窗)
  const [pendingDeleteProvider, setPendingDeleteProvider] = useState<AIProvider | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const group = await listProvidersByType(tab);
      setGrouped(group);
    } catch (e) {
      showToast(`加载失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [tab, showToast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onActivate = useCallback(async (provider: AIProvider, vendor: VendorGroup | null) => {
    if (provider.is_active) return;
    if (!provider.enabled) {
      showToast('请先启用此 Provider');
      return;
    }
    if (vendor && !vendor.has_credential) {
      showToast(`${vendor.name} 凭证未配置, 先点 [配置凭证]`);
      setCredentialsForVendor(vendor);
      return;
    }
    try {
      await activateProvider(provider.id);
      showToast(`已切换到 ${provider.name}, 下条对话生效`);
      await refresh();
    } catch (e) {
      showToast(`切换失败：${(e as Error).message}`);
    }
  }, [showToast, refresh]);

  const onToggleEnabled = useCallback(async (provider: AIProvider) => {
    try {
      await updateProvider(provider.id, { enabled: !provider.enabled });
      await refresh();
    } catch (e) {
      showToast(`更新失败：${(e as Error).message}`);
    }
  }, [showToast, refresh]);

  // bugfix-3.2.8: 删 provider 走自定义 ConfirmDialog (而不是 confirm()),与
  // 删 vendor 走同一个 UI pattern。
  const onConfirmDeleteProvider = useCallback(async () => {
    if (!pendingDeleteProvider) return;
    const p = pendingDeleteProvider;
    setPendingDeleteProvider(null);
    try {
      await deleteProvider(p.id);
      showToast(`已删除 ${p.name}`);
      await refresh();
    } catch (e) {
      showToast(`删除失败：${(e as Error).message}`);
    }
  }, [pendingDeleteProvider, showToast, refresh]);

  const onConfirmDeleteVendor = useCallback(async () => {
    if (!pendingDeleteVendor) return;
    try {
      await deleteVendor(pendingDeleteVendor.id);
      showToast(`已删除 Vendor ${pendingDeleteVendor.name}`);
      setPendingDeleteVendor(null);
      await refresh();
    } catch (e) {
      showToast(`删除失败：${(e as Error).message}`);
      setPendingDeleteVendor(null);
    }
  }, [pendingDeleteVendor, showToast, refresh]);

  // Vendor cards 列表 — 当前 tab 下所有有 provider 的 vendor + 空 vendor
  // (用户可能配了 vendor 但没 provider) 也展示, 用 + 按钮诱导加 provider。
  const vendorGroups: VendorGroup[] = useMemo(() => grouped?.vendors ?? [], [grouped]);
  const ungrouped: AIProvider[] = useMemo(() => grouped?.ungrouped ?? [], [grouped]);

  return (
    <div className="p-6 max-w-3xl">
      <h2
        className="text-lg font-medium mb-1"
        style={{ color: 'var(--color-text-primary)' }}
      >
        🧠 AI Providers
      </h2>
      <p
        className="text-xs mb-4"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        按 Vendor 分组管理 LLM / ASR / TTS。一组凭证供同 vendor 下所有 model 共享。
      </p>

      {/* Tabs */}
      <div
        className="inline-flex rounded-md p-0.5 mb-4"
        style={{
          background: 'var(--color-bg-input)',
          border: '1px solid var(--color-border)',
        }}
      >
        {TABS.map((t) => {
          const active = t.id === tab;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
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
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Vendor groups */}
      {loading && vendorGroups.length === 0 ? (
        <div
          className="text-sm py-12 text-center"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          加载中…
        </div>
      ) : vendorGroups.length === 0 && ungrouped.length === 0 && tab === 'llm' ? (
        <div
          className="text-sm py-12 text-center"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          还没有 LLM Provider。
        </div>
      ) : tab === 'asr' ? (
        // bugfix-3.3 (light): Faster Whisper 卡 + VAD 现有控件。ASR provider
        // 不入 DB ai_providers (本 stage 用户拍板:单 backend, 不需 dispatcher
        // 抽象)。model_size 切换走 POST /api/config/asr → yaml; 下次 transcribe
        // 触发 whisper reload。
        <div className="space-y-3">
          <FasterWhisperCard showToast={showToast} />
          <AsrVadSection />
        </div>
      ) : tab === 'tts' ? (
        // bugfix-3.3 (light): CosyVoice 卡 (绑 Qwen vendor 凭证) + voice 下拉 +
        // TTS 总开关。2026-06-06:加 GSV + Fish 卡(方案 A · hardcoded JSX 同款,
        // 不动 DB ai_providers)· 数据走 GET /api/tts/providers · 绑定到角色仍
        // 走 CharacterPanel VoicePicker(voice_model JSON per-character)。
        <div className="space-y-3">
          <CosyVoiceTTSCard
            showToast={showToast}
            onConfigureQwenCred={(qwenVendor) => setCredentialsForVendor(qwenVendor)}
          />
          <GsvTTSCard />
          <FishTTSCard />
          <TtsSection showToast={showToast} />
        </div>
      ) : (
        <div className="space-y-3">
          {/* bugfix-3.2.8: 4 个 builtin vendor 始终显示 (不再 filter providers.length>0
              的卡 — 即使 provider 列表空, 也露 "+ 添加 X 模型" 按钮诱导用户加 model)。
              custom vendor 自然也都显示。 */}
          {vendorGroups.map((v) => (
            <VendorCard
              key={v.id}
              vendor={v}
              tab={tab}
              onConfigureCredentials={() => setCredentialsForVendor(v)}
              onDeleteVendor={() => setPendingDeleteVendor(v)}
              onAddModel={() => setAddModelForVendor(v)}
              onActivate={(p) => onActivate(p, v)}
              onToggleEnabled={onToggleEnabled}
              onDeleteProvider={(p) => setPendingDeleteProvider(p)}
            />
          ))}

          {ungrouped.length > 0 && (
            <UngroupedCard
              providers={ungrouped}
              onActivate={(p) => onActivate(p, null)}
              onToggleEnabled={onToggleEnabled}
              onDeleteProvider={(p) => setPendingDeleteProvider(p)}
            />
          )}
        </div>
      )}

      {/* bugfix-3.2.8: 顶层"添加自定义 Vendor" — 跟 vendor card 内"添加模型"
          概念分开。仅 llm tab 显示 (ASR/TTS 还在 3.3 时再加)。 */}
      {tab === 'llm' && (
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => setAddVendorOpen(true)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            <Plus size={14} /> 添加自定义 Vendor
          </button>
        </div>
      )}

      {/* Modals */}
      {addModelForVendor && (
        <AddModelModal
          vendor={addModelForVendor}
          type={tab}
          onClose={() => setAddModelForVendor(null)}
          onSaved={() => {
            setAddModelForVendor(null);
            void refresh();
          }}
          showToast={showToast}
        />
      )}
      {addVendorOpen && (
        <AddVendorModal
          onClose={() => setAddVendorOpen(false)}
          onSaved={() => {
            setAddVendorOpen(false);
            void refresh();
          }}
          showToast={showToast}
        />
      )}
      {credentialsForVendor && (
        <VendorCredentialsModal
          vendor={credentialsForVendor}
          onClose={() => setCredentialsForVendor(null)}
          onSaved={() => {
            setCredentialsForVendor(null);
            void refresh();
          }}
          showToast={showToast}
        />
      )}
      {pendingDeleteVendor && (
        <ConfirmDialog
          title={`删除 Vendor ${pendingDeleteVendor.name}?`}
          body={`这会一并删除该 Vendor 的凭证。在它下面的 Provider 会变成"未分组"。不可撤销。`}
          danger
          onCancel={() => setPendingDeleteVendor(null)}
          onConfirm={onConfirmDeleteVendor}
        />
      )}
      {pendingDeleteProvider && (
        <ConfirmDialog
          title={`删除 ${pendingDeleteProvider.name}?`}
          body={`Model: ${pendingDeleteProvider.model}\n不可撤销。`}
          danger
          onCancel={() => setPendingDeleteProvider(null)}
          onConfirm={onConfirmDeleteProvider}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// VendorCard
// ---------------------------------------------------------------------------

interface VendorCardProps {
  vendor: VendorGroup;
  tab: ProviderType;
  onConfigureCredentials: () => void;
  onDeleteVendor: () => void;
  onAddModel: () => void;
  onActivate: (provider: AIProvider) => void;
  onToggleEnabled: (provider: AIProvider) => void;
  onDeleteProvider: (provider: AIProvider) => void;
}

function VendorCard({
  vendor,
  tab,
  onConfigureCredentials,
  onDeleteVendor,
  onAddModel,
  onActivate,
  onToggleEnabled,
  onDeleteProvider,
}: VendorCardProps) {
  const isBuiltin = vendor.vendor_kind === 'builtin';

  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      {/* Vendor header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span
            className="inline-block w-3 h-3 rounded-full shrink-0"
            style={{ background: vendor.color ?? 'var(--color-text-secondary)' }}
          />
          <span
            className="text-sm font-medium truncate"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {vendor.name}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-secondary)',
            }}
          >
            {vendor.vendor_kind}
          </span>
          {vendor.credential_source === 'db' ? (
            <span
              className="text-[11px] flex items-center gap-1 shrink-0"
              style={{ color: 'var(--color-text-accent)' }}
              title="凭证存于本地 SQLite (Fernet 加密)"
            >
              <CheckCircle2 size={12} /> 凭证已配置
            </span>
          ) : vendor.credential_source === 'env' ? (
            <span
              className="text-[11px] flex items-center gap-1 shrink-0"
              style={{ color: 'var(--color-text-accent)' }}
              title=".env 文件提供的凭证 — 进程启动时读取"
            >
              <CheckCircle2 size={12} /> 凭证已配置 (.env)
            </span>
          ) : (
            <span
              className="text-[11px] flex items-center gap-1 shrink-0"
              style={{ color: 'rgb(245,158,11)' }}
            >
              <AlertTriangle size={12} /> 凭证未配置
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={onConfigureCredentials}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded transition"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
            title={
              vendor.credential_source === 'env'
                ? '当前用 .env 凭证; 点此改用 DB 凭证 (优先级更高)'
                : undefined
            }
          >
            <KeyRound size={12} /> {
              vendor.credential_source === 'db' ? '更新凭证'
                : vendor.credential_source === 'env' ? '改用 DB 凭证'
                  : '配置凭证'
            }
          </button>
          {!isBuiltin && (
            <button
              type="button"
              onClick={onDeleteVendor}
              className="p-1.5 rounded transition"
              style={{ color: 'rgb(244,63,94)' }}
              title="删除 Vendor"
            >
              <Trash2 size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Provider rows */}
      {vendor.providers.length === 0 ? (
        <div
          className="text-xs italic px-2 py-3"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {vendor.has_credential
            ? '凭证已配,点下方 [+ 添加模型] 加一个 model 即可启用。'
            : '凭证未配置,先点 [配置凭证]; 然后点下方 [+ 添加模型] 加 model。'}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {vendor.providers.map((p) => (
            <ProviderRow
              key={p.id}
              provider={p}
              onActivate={() => onActivate(p)}
              onToggleEnabled={() => onToggleEnabled(p)}
              onDelete={() => onDeleteProvider(p)}
            />
          ))}
        </ul>
      )}

      {/* bugfix-3.2.8: vendor card 内独立"+ 添加 X 模型"按钮。仅 llm tab 显示。 */}
      {tab === 'llm' && (
        <div className="mt-2.5">
          <button
            type="button"
            onClick={onAddModel}
            className="flex items-center gap-1 text-[11px] px-2 py-1 rounded transition"
            style={{
              background: 'transparent',
              border: '1px dashed var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
          >
            <Plus size={11} /> 添加 {vendor.name} 模型
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ProviderRow
// ---------------------------------------------------------------------------

interface ProviderRowProps {
  provider: AIProvider;
  onActivate: () => void;
  onToggleEnabled: () => void;
  onDelete: () => void;
}

function ProviderRow({ provider, onActivate, onToggleEnabled, onDelete }: ProviderRowProps) {
  // bugfix-3.2.8: builtin / custom 都允许删 — 按钮总显示 (老逻辑 hide builtin)。
  return (
    <li
      className="rounded-md px-3 py-2 flex items-center gap-3"
      style={{
        background: provider.is_active
          ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
          : 'var(--color-bg-input)',
        border: provider.is_active
          ? '1px solid var(--color-accent)'
          : '1px solid var(--color-border-subtle)',
      }}
    >
      <button
        type="button"
        onClick={onActivate}
        disabled={provider.is_active}
        className="shrink-0 flex items-center justify-center"
        style={{
          color: provider.is_active
            ? 'var(--color-text-accent)'
            : 'var(--color-text-secondary)',
          cursor: provider.is_active ? 'default' : 'pointer',
        }}
        title={provider.is_active ? '当前 active' : '切换到该 Provider'}
        aria-label={provider.is_active ? '当前 active' : '激活'}
      >
        {provider.is_active ? <CheckCircle2 size={16} /> : <Circle size={16} />}
      </button>

      <div className="flex-1 min-w-0">
        <div
          className="text-sm truncate"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {provider.name}
          {provider.is_active && (
            <span
              className="ml-2 text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-bubble-user-text)',
              }}
            >
              active
            </span>
          )}
        </div>
        <div
          className="text-[11px] font-mono truncate"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {provider.model}
        </div>
      </div>

      <label
        className="flex items-center gap-1.5 text-[11px] shrink-0"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        <input
          type="checkbox"
          checked={provider.enabled}
          onChange={onToggleEnabled}
          className="cursor-pointer"
          style={{ accentColor: 'var(--color-accent)' }}
        />
        启用
      </label>

      <button
        type="button"
        onClick={onDelete}
        className="p-1 rounded transition shrink-0"
        style={{ color: 'rgb(244,63,94)' }}
        title="删除"
      >
        <Trash2 size={12} />
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
// UngroupedCard — vendor_id=null 的 provider (eg 单 ASR provider)
// ---------------------------------------------------------------------------

interface UngroupedCardProps {
  providers: AIProvider[];
  onActivate: (provider: AIProvider) => void;
  onToggleEnabled: (provider: AIProvider) => void;
  onDeleteProvider: (provider: AIProvider) => void;
}

function UngroupedCard({ providers, onActivate, onToggleEnabled, onDeleteProvider }: UngroupedCardProps) {
  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 40%, transparent)',
        border: '1px dashed var(--color-border-subtle)',
      }}
    >
      <h4
        className="text-xs font-medium mb-2"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        未分组 Provider
      </h4>
      <ul className="space-y-1.5">
        {providers.map((p) => (
          <ProviderRow
            key={p.id}
            provider={p}
            onActivate={() => onActivate(p)}
            onToggleEnabled={() => onToggleEnabled(p)}
            onDelete={() => onDeleteProvider(p)}
          />
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ConfirmDialog (复用 mcp pattern)
// ---------------------------------------------------------------------------

interface ConfirmDialogProps {
  title: string;
  body: string;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

function ConfirmDialog({ title, body, danger, onCancel, onConfirm }: ConfirmDialogProps) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center"
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
        <h4
          className="text-sm font-semibold mb-2"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {title}
        </h4>
        <p
          className="text-xs mb-4"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {body}
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
            className="px-3 py-1.5 text-xs rounded-md transition text-white"
            style={{
              background: danger ? 'rgb(244,63,94)' : 'var(--color-accent)',
            }}
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Bugfix-3.3 — FasterWhisperCard (ASR tab)
// ---------------------------------------------------------------------------

const _BACKEND_BASE = 'http://127.0.0.1:8000';

interface AsrConfigResponse {
  whisper_model_size: string;
  allowed_sizes: string[];
}

interface FasterWhisperCardProps {
  showToast: (text: string) => void;
}

// 本 stage 用户拍板:UI 只暴露 small / medium 两档,其他 size 留 v4.1+。
const _ASR_UI_SIZES = ['small', 'medium'] as const;

function FasterWhisperCard({ showToast }: FasterWhisperCardProps) {
  const [size, setSize] = useState<string>('small');
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${_BACKEND_BASE}/api/config/asr`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as AsrConfigResponse;
        if (cancelled) return;
        setSize(j.whisper_model_size);
        setLoaded(true);
      } catch (e) {
        showToast(`加载 ASR 配置失败：${(e as Error).message}`);
        setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [showToast]);

  const onChange = useCallback(async (next: string) => {
    if (next === size || busy) return;
    const prev = size;
    setSize(next);  // optimistic
    setBusy(true);
    try {
      const r = await fetch(`${_BACKEND_BASE}/api/config/asr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ whisper_model_size: next }),
      });
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (j?.detail) detail = String(j.detail);
        } catch { /* ignore */ }
        throw new Error(detail);
      }
      showToast(`Whisper model_size → ${next}; 下次录音重新加载`);
    } catch (e) {
      setSize(prev);
      showToast(`切换失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }, [size, busy, showToast]);

  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <Mic size={16} style={{ color: 'var(--color-text-accent)' }} />
          <span
            className="text-sm font-medium truncate"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Faster Whisper (本地)
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-secondary)',
            }}
          >
            builtin
          </span>
        </div>
      </div>

      <div className="space-y-2">
        <div>
          <label className="block text-xs mb-1"
            style={{ color: 'var(--color-text-primary)' }}>
            Model 大小
          </label>
          {!loaded ? (
            <div className="text-xs"
              style={{ color: 'var(--color-text-secondary)' }}>
              加载中…
            </div>
          ) : (
            <div className="flex gap-2">
              {_ASR_UI_SIZES.map((s) => {
                const active = s === size;
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void onChange(s)}
                    disabled={busy}
                    className="text-xs px-3 py-1.5 rounded-md transition disabled:opacity-50"
                    style={
                      active
                        ? {
                            background: 'var(--color-accent)',
                            color: 'var(--color-bubble-user-text)',
                          }
                        : {
                            background: 'var(--color-bg-input)',
                            border: '1px solid var(--color-border)',
                            color: 'var(--color-text-primary)',
                          }
                    }
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          )}
          <div className="text-[10px] mt-1"
            style={{ color: 'var(--color-text-secondary)' }}>
            small 快 / 体积小; medium 准 / 加载稍慢。切换后下次录音才 reload。
          </div>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Bugfix-3.3 — CosyVoiceTTSCard (TTS tab)
// ---------------------------------------------------------------------------

interface SystemVoiceRow {
  id: string;
  label: string;
  traits: string;
  instruct: boolean | null;
}

interface ClonedVoiceRow {
  voice_id: string;
  status?: string | null;
  update_time?: string | null;
}

interface UsageMap {
  [voiceId: string]: Array<{ id: number; name: string }>;
}

interface CosyVoiceTTSCardProps {
  showToast: (text: string) => void;
  onConfigureQwenCred: (qwenVendor: AIVendor) => void;
}

function CosyVoiceTTSCard({ showToast, onConfigureQwenCred }: CosyVoiceTTSCardProps) {
  const [qwenVendor, setQwenVendor] = useState<AIVendor | null>(null);
  const [systemVoices, setSystemVoices] = useState<SystemVoiceRow[]>([]);
  const [clonedVoices, setClonedVoices] = useState<ClonedVoiceRow[]>([]);
  const [usage, setUsage] = useState<UsageMap>({});
  const [loadingCloned, setLoadingCloned] = useState(false);
  // bugfix-3.4: aliases map (voice_id → display_name) + inline rename state
  const [aliases, setAliases] = useState<Record<string, string>>({});
  const [renamingVoice, setRenamingVoice] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState<string>('');
  // 试听播放状态:正在播的 voice id;null = 无播放
  const [playingId, setPlayingId] = useState<string | null>(null);
  // bugfix-4 (4.2): TTS 用量 panel state
  const [usagePanelOpen, setUsagePanelOpen] = useState(false);
  const [recentModalOpen, setRecentModalOpen] = useState(false);
  // ref to current Audio so toggling 暂停 / 切歌 都能停老的
  const audioRef = (typeof window !== 'undefined')
    ? (window as unknown as { _ttsAudio?: HTMLAudioElement | null })
    : ({} as { _ttsAudio?: HTMLAudioElement | null });

  const refreshUsage = useCallback(async () => {
    try {
      const r = await fetch(`${_BACKEND_BASE}/api/tts/voices/usage`);
      if (!r.ok) return;
      const j = await r.json() as { by_voice: Array<{ voice: string; characters: Array<{ id: number; name: string }> }> };
      const m: UsageMap = {};
      for (const e of j.by_voice) m[e.voice] = e.characters;
      setUsage(m);
    } catch {/* ignore */}
  }, []);

  const refreshAliases = useCallback(async () => {
    try {
      const m = await fetchVoiceAliases();
      setAliases(m);
    } catch {/* ignore */}
  }, []);

  const onSubmitRename = useCallback(async (voiceId: string) => {
    const next = renameDraft.trim();
    if (!next) {
      setRenamingVoice(null);
      return;
    }
    try {
      await setVoiceAlias(voiceId, next);
      setAliases((m) => ({ ...m, [voiceId]: next }));
      showToast(`已重命名 → ${next}`);
    } catch (e) {
      showToast(`重命名失败:${(e as Error).message}`);
    } finally {
      setRenamingVoice(null);
    }
  }, [renameDraft, showToast]);

  const refreshCloned = useCallback(async (force: boolean) => {
    setLoadingCloned(true);
    try {
      const url = `${_BACKEND_BASE}/api/tts/voices/cloned${force ? '?force=1' : ''}`;
      const r = await fetch(url);
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (j?.detail) detail = String(j.detail);
        } catch {/* ignore */}
        throw new Error(detail);
      }
      const j = await r.json() as { voices: ClonedVoiceRow[] };
      setClonedVoices(j.voices);
    } catch (e) {
      showToast(`复刻 voice 加载失败:${(e as Error).message}`);
    } finally {
      setLoadingCloned(false);
    }
  }, [showToast]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // 1. Qwen vendor cred 状态 (CosyVoice 走 DashScope, 复用 Qwen vendor 的 key)
        const r1 = await fetch(`${_BACKEND_BASE}/api/ai-vendors`);
        if (r1.ok) {
          const vList = (await r1.json()) as AIVendor[];
          if (!cancelled) {
            setQwenVendor(vList.find((v) => v.id === 'qwen') ?? null);
          }
        }
        // 2. 系统 voice 列表 (yaml::tts.available_voices.cosyvoice)
        const r2 = await fetch(`${_BACKEND_BASE}/api/tts/voices`);
        if (r2.ok) {
          const j = await r2.json() as { providers: Array<{ id: string; voices: SystemVoiceRow[] }> };
          if (!cancelled) {
            const cosy = j.providers.find((p) => p.id === 'cosyvoice');
            setSystemVoices(cosy?.voices ?? []);
          }
        }
        // 3. (bugfix-4 4.5) 删除 default voice 状态 — UI 不再暴露 [设为全局默认]
        // 4. usage 反向索引
        await refreshUsage();
        // 5. 复刻 voice (走缓存)
        await refreshCloned(false);
        // 6. bugfix-3.4: alias map
        await refreshAliases();
      } catch (e) {
        if (!cancelled) {
          showToast(`加载 CosyVoice 配置失败:${(e as Error).message}`);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [showToast, refreshUsage, refreshCloned, refreshAliases]);

  const onPreview = useCallback(async (voiceId: string) => {
    // 已在播这个 voice → 暂停
    if (playingId === voiceId && audioRef._ttsAudio) {
      audioRef._ttsAudio.pause();
      audioRef._ttsAudio = null;
      setPlayingId(null);
      return;
    }
    // 切到别的 voice
    if (audioRef._ttsAudio) {
      audioRef._ttsAudio.pause();
      audioRef._ttsAudio = null;
    }
    setPlayingId(voiceId);
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
        } catch {/* ignore */}
        throw new Error(detail);
      }
      const j = await r.json() as { audio_b64: string };
      const a = new Audio(`data:audio/wav;base64,${j.audio_b64}`);
      audioRef._ttsAudio = a;
      a.onended = () => {
        if (audioRef._ttsAudio === a) {
          audioRef._ttsAudio = null;
          setPlayingId((cur) => (cur === voiceId ? null : cur));
        }
      };
      await a.play();
    } catch (e) {
      showToast(`试听失败:${(e as Error).message}`);
      setPlayingId(null);
    }
  }, [playingId, audioRef, showToast]);

  // bugfix-4 (4.5): 删除 [设为全局默认] — per-character voice 已 work,全局
  // fallback 字段 tts.cosyvoice.default_voice 仍保留 yaml 兜底,只是不暴露 UI
  // 控件 (用户拍板:per-character 都配后,全局无人改)。

  // 2026-06-07 · 改用 TtsCardShell · 外框 + header 抽到 shell · 凭证 ✓/⚠ 徽标
  // 进 statusBadge · 配置凭证 + 刷新复刻两个按钮进 headerActions(shell 内已
  // stopPropagation 防点击 toggle expand)· body 完全不动(系统/复刻/用量/modal)。
  const statusBadge = (
    <>
      <span
        className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0"
        style={{
          background: 'var(--color-bg-elevated)',
          color: 'var(--color-text-secondary)',
        }}
      >
        builtin
      </span>
      {qwenVendor?.has_credential ? (
        <span
          className="text-[11px] flex items-center gap-1 shrink-0"
          style={{ color: 'var(--color-text-accent)' }}
          title={
            qwenVendor.credential_source === 'env'
              ? '复用 Qwen vendor .env 凭证 (DASHSCOPE_API_KEY)'
              : '复用 Qwen vendor DB 凭证'
          }
        >
          <CheckCircle2 size={12} /> 凭证已配置 (复用 Qwen)
        </span>
      ) : (
        <span
          className="text-[11px] flex items-center gap-1 shrink-0"
          style={{ color: 'rgb(245,158,11)' }}
        >
          <AlertTriangle size={12} /> 未配置 (需 Qwen 凭证)
        </span>
      )}
    </>
  );

  const headerActions = (
    <>
      {qwenVendor && !qwenVendor.has_credential && (
        <button
          type="button"
          onClick={() => onConfigureQwenCred(qwenVendor)}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded transition"
          style={{
            background: 'var(--color-bg-input)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-primary)',
          }}
        >
          <KeyRound size={12} /> 配置 Qwen 凭证
        </button>
      )}
      <button
        type="button"
        onClick={() => void refreshCloned(true)}
        disabled={loadingCloned}
        className="flex items-center gap-1 text-[11px] px-2 py-1 rounded transition disabled:opacity-50"
        style={{
          background: 'transparent',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-secondary)',
        }}
        title="强制刷新 DashScope 复刻列表 (跳过 5min 缓存)"
      >
        🔄 刷新复刻列表
      </button>
    </>
  );

  return (
    <TtsCardShell
      icon={Volume2}
      title="CosyVoice (DashScope)"
      statusBadge={statusBadge}
      headerActions={headerActions}
    >

      {/* 系统 voice */}
      <div className="mb-4">
        <h5 className="text-[11px] font-medium uppercase tracking-wide mb-1.5"
          style={{ color: 'var(--color-text-secondary)' }}>
          系统音色 ({systemVoices.length})
        </h5>
        <ul className="space-y-1.5">
          {systemVoices.map((v) => (
            <TtsGalleryRow
              key={v.id}
              voiceId={v.id}
              label={v.label}
              sub={v.traits + (v.instruct ? ' · 支持情感' : '')}
              kindLabel="系统"
              playing={playingId === v.id}
              usage={usage[v.id]}
              onPreview={() => void onPreview(v.id)}
            />
          ))}
        </ul>
      </div>

      {/* 用户复刻 voice */}
      <div>
        <h5 className="text-[11px] font-medium uppercase tracking-wide mb-1.5"
          style={{ color: 'var(--color-text-secondary)' }}>
          用户复刻 {loadingCloned ? '(加载中…)' : `(${clonedVoices.length})`}
        </h5>
        {clonedVoices.length === 0 && !loadingCloned && (
          <div className="text-[11px] italic px-2 py-2"
            style={{ color: 'var(--color-text-secondary)' }}>
            没有复刻 voice。在 DashScope 控制台 (model-studio.console.aliyun.com)
            复刻后,这里按 [🔄 刷新复刻列表] 拉新。
          </div>
        )}
        <ul className="space-y-1.5">
          {clonedVoices.map((v) => {
            const isRenaming = renamingVoice === v.voice_id;
            const friendly = resolveVoiceName(v.voice_id, aliases);
            return (
              <TtsGalleryRow
                key={v.voice_id}
                voiceId={v.voice_id}
                // bugfix-3.4: 用友好名 (alias 优先 / fallback 截断 id)
                label={friendly}
                sub={`复刻 · cosyvoice-v3.5-plus · ${v.status ?? '?'}${v.update_time ? ' · ' + v.update_time : ''}`}
                kindLabel="复刻"
                playing={playingId === v.voice_id}
                usage={usage[v.voice_id]}
                onPreview={() => void onPreview(v.voice_id)}
                // bugfix-3.4: 重命名相关
                isRenaming={isRenaming}
                renameDraft={renameDraft}
                onStartRename={() => {
                  setRenameDraft(friendly);
                  setRenamingVoice(v.voice_id);
                }}
                onChangeRenameDraft={setRenameDraft}
                onSubmitRename={() => void onSubmitRename(v.voice_id)}
                onCancelRename={() => setRenamingVoice(null)}
                // bugfix-3.4: v3.5-plus 模型 banner
                noteText="ⓘ cosyvoice-v3.5-plus, 暂无情绪表达 (v4.1+)"
              />
            );
          })}
        </ul>
      </div>

      <div className="text-[10px] mt-3"
        style={{ color: 'var(--color-text-secondary)' }}>
        角色级 voice 在 ⚙ 设置 → 角色管理 内单独配; gallery 仅用于试听 + 反向
        查看哪个角色用了哪个 voice。
      </div>

      {/* bugfix-4 (4.2): TTS 用量 panel — 折叠面板 */}
      <div className="mt-4 pt-3"
        style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
        <button
          type="button"
          onClick={() => setUsagePanelOpen((v) => !v)}
          className="flex items-center justify-between w-full text-xs"
          style={{ color: 'var(--color-text-primary)' }}
        >
          <span>📊 今日 TTS 用量 (CosyVoice)</span>
          <span style={{ color: 'var(--color-text-secondary)' }}>
            {usagePanelOpen ? '▼ 收起' : '▶ 展开'}
          </span>
        </button>
        {usagePanelOpen && (
          <TtsUsagePanel
            showToast={showToast}
            onOpenRecent={() => setRecentModalOpen(true)}
          />
        )}
      </div>

      {recentModalOpen && (
        <RecentCallsModal
          onClose={() => setRecentModalOpen(false)}
          showToast={showToast}
        />
      )}
    </TtsCardShell>
  );
}


// ---------------------------------------------------------------------------
// Bugfix-4 (4.2) — TtsUsagePanel: 今日/本月用量 + by_source + anomaly hint
// ---------------------------------------------------------------------------

interface TtsUsagePanelProps {
  showToast: (text: string) => void;
  onOpenRecent: () => void;
}

function TtsUsagePanel({ showToast, onOpenRecent }: TtsUsagePanelProps) {
  const [range, setRange] = useState<UsageRange>('today');
  const [usage, setUsage] = useState<TtsUsage | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const u = await fetchTtsUsage(range);
      setUsage(u);
    } catch (e) {
      showToast(`加载用量失败:${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [range, showToast]);

  useEffect(() => { void load(); }, [load]);

  if (loading && !usage) {
    return <div className="text-[11px] mt-2"
      style={{ color: 'var(--color-text-secondary)' }}>加载中…</div>;
  }
  if (!usage) return null;

  const sources = Object.entries(usage.by_source);
  return (
    <div className="mt-2 text-[11px]">
      {/* range selector */}
      <div className="flex items-center gap-1 mb-2">
        {(['today', 'month'] as const).map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setRange(r)}
            className="text-[10px] px-2 py-0.5 rounded"
            style={{
              background: range === r
                ? 'var(--color-accent)'
                : 'var(--color-bg-input)',
              color: range === r
                ? 'var(--color-bubble-user-text)'
                : 'var(--color-text-primary)',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            {r === 'today' ? '今日' : '本月'}
          </button>
        ))}
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="text-[10px] px-2 py-0.5 rounded ml-auto"
          style={{
            background: 'var(--color-bg-input)',
            border: '1px solid var(--color-border-subtle)',
            color: 'var(--color-text-secondary)',
          }}
          title="刷新"
        >
          🔄 刷新
        </button>
        <button
          type="button"
          onClick={onOpenRecent}
          className="text-[10px] px-2 py-0.5 rounded"
          style={{
            background: 'var(--color-bg-input)',
            border: '1px solid var(--color-border-subtle)',
            color: 'var(--color-text-secondary)',
          }}
        >
          详细记录
        </button>
      </div>

      {sources.length === 0 ? (
        <div style={{ color: 'var(--color-text-secondary)' }}>
          {range === 'today' ? '今日' : '本月'}还没有 TTS 调用记录。
        </div>
      ) : (
        <table className="w-full">
          <tbody>
            {sources.map(([k, v]) => (
              <tr key={k}>
                <td className="py-0.5"
                  style={{ color: 'var(--color-text-primary)' }}>
                  {sourceLabel(k)}
                </td>
                <td className="py-0.5 text-right font-mono"
                  style={{ color: 'var(--color-text-secondary)' }}>
                  {v.chars.toLocaleString()} chars
                </td>
                <td className="py-0.5 text-right font-mono pl-2"
                  style={{ color: 'var(--color-text-secondary)' }}>
                  ¥{v.cost.toFixed(3)}
                </td>
              </tr>
            ))}
            <tr style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
              <td className="py-0.5 pt-1.5"
                style={{ color: 'var(--color-text-primary)' }}>
                总计 ({usage.total_calls} 次调用)
              </td>
              <td className="py-0.5 pt-1.5 text-right font-mono"
                style={{ color: 'var(--color-text-accent)' }}>
                {usage.total_chars.toLocaleString()} chars
              </td>
              <td className="py-0.5 pt-1.5 text-right font-mono pl-2"
                style={{ color: 'var(--color-text-accent)' }}>
                ¥{usage.total_cost_yuan.toFixed(3)}
              </td>
            </tr>
          </tbody>
        </table>
      )}

      {usage.anomaly_calls.length > 0 && (
        <div className="mt-2 px-2 py-1.5 rounded"
          style={{
            background: 'color-mix(in srgb, rgb(245,158,11) 12%, transparent)',
            color: 'rgb(245,158,11)',
            border: '1px solid rgba(245,158,11,0.3)',
          }}>
          ⚠ 检测到 {usage.anomaly_calls.length} 次异常长 call (input_chars &gt; 500),
          可能 thinking/state tag 漏进 TTS。点 [详细记录] 抓样诊断。
        </div>
      )}
      {usage.avg_chars_per_call !== null && (
        <div className="mt-1.5 text-[10px]"
          style={{ color: 'var(--color-text-secondary)' }}>
          平均每次 {usage.avg_chars_per_call} chars · 估算非精确账单
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Bugfix-4 (4.2) — RecentCallsModal: 抓样查 input_preview
// ---------------------------------------------------------------------------

interface RecentCallsModalProps {
  onClose: () => void;
  showToast: (text: string) => void;
}

function RecentCallsModal({ onClose, showToast }: RecentCallsModalProps) {
  const [calls, setCalls] = useState<RecentCall[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const c = await fetchRecentCalls(50);
        if (!cancelled) setCalls(c);
      } catch (e) {
        if (!cancelled) showToast(`加载 recent calls 失败:${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [showToast]);

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[640px] max-h-[80vh] overflow-y-auto shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-semibold"
            style={{ color: 'var(--color-text-primary)' }}>
            最近 TTS 调用 ({calls.length})
          </h4>
          <button onClick={onClose}
            className="text-xs px-2 py-1 rounded"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}>关闭</button>
        </div>
        {loading && (
          <div className="text-xs"
            style={{ color: 'var(--color-text-secondary)' }}>加载中…</div>
        )}
        <ul className="space-y-1">
          {calls.map((c) => {
            const isAnomaly = c.input_chars > 500;
            const isExpanded = expandedId === c.id;
            return (
              <li key={c.id}
                className="rounded px-2 py-1.5 text-[11px]"
                style={{
                  background: isAnomaly
                    ? 'color-mix(in srgb, rgb(245,158,11) 8%, transparent)'
                    : 'var(--color-bg-input)',
                  border: '1px solid var(--color-border-subtle)',
                }}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono shrink-0"
                    style={{ color: 'var(--color-text-secondary)' }}>
                    {(c.timestamp ?? '').slice(0, 19)}
                  </span>
                  <span className="px-1 rounded shrink-0"
                    style={{
                      background: 'var(--color-bg-elevated)',
                      color: 'var(--color-text-primary)',
                    }}>
                    {sourceLabel(c.source)}
                  </span>
                  {!c.success && (
                    <span className="px-1 rounded shrink-0"
                      style={{
                        background: 'rgb(244,63,94)',
                        color: 'white',
                      }}>FAIL</span>
                  )}
                  <span className="font-mono shrink-0"
                    style={{
                      color: isAnomaly ? 'rgb(245,158,11)'
                                       : 'var(--color-text-secondary)',
                    }}>
                    {c.input_chars} chars · ¥{(c.cost_estimate ?? 0).toFixed(4)}
                  </span>
                  <button
                    type="button"
                    onClick={() => setExpandedId(isExpanded ? null : c.id)}
                    className="text-[10px] ml-auto shrink-0"
                    style={{ color: 'var(--color-text-accent)' }}>
                    {isExpanded ? '收起' : '▶ 抓样查看'}
                  </button>
                </div>
                {isExpanded && c.input_preview && (
                  <div className="mt-1 px-2 py-1 rounded font-mono whitespace-pre-wrap break-words"
                    style={{
                      background: 'var(--color-bg-elevated)',
                      color: 'var(--color-text-primary)',
                      maxHeight: '200px',
                      overflow: 'auto',
                    }}>
                    {c.input_preview}
                  </div>
                )}
                {isExpanded && c.error_message && (
                  <div className="mt-1 text-[10px]"
                    style={{ color: 'rgb(244,63,94)' }}>
                    ERR: {c.error_message}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// TtsGalleryRow — shared row for system / cloned voice
// ---------------------------------------------------------------------------

interface TtsGalleryRowProps {
  voiceId: string;
  label: string;
  sub: string;
  kindLabel: string;
  playing: boolean;
  usage?: Array<{ id: number; name: string }>;
  onPreview: () => void;
  // bugfix-3.4: 重命名相关 (仅复刻 voice 显示按钮)
  isRenaming?: boolean;
  renameDraft?: string;
  onStartRename?: () => void;
  onChangeRenameDraft?: (next: string) => void;
  onSubmitRename?: () => void;
  onCancelRename?: () => void;
  noteText?: string;  // bugfix-3.4: 行底 small note (v3.5-plus 无 emotion 等)
}

function TtsGalleryRow({
  voiceId, label, sub, kindLabel, playing,
  usage, onPreview,
  isRenaming, renameDraft, onStartRename, onChangeRenameDraft,
  onSubmitRename, onCancelRename, noteText,
}: TtsGalleryRowProps) {
  const canRename = !!onStartRename;
  return (
    <li
      className="rounded-md px-3 py-2 flex flex-col gap-1"
      style={{
        background: 'var(--color-bg-input)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            {isRenaming ? (
              <>
                <input
                  type="text"
                  value={renameDraft ?? ''}
                  onChange={(e) => onChangeRenameDraft?.(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') onSubmitRename?.();
                    else if (e.key === 'Escape') onCancelRename?.();
                  }}
                  autoFocus
                  className="text-sm rounded px-1.5 py-0.5 focus:outline-none flex-1 min-w-0"
                  style={{
                    background: 'var(--color-bg-elevated)',
                    border: '1px solid var(--color-accent)',
                    color: 'var(--color-text-primary)',
                  }}
                  maxLength={64}
                />
                <button
                  type="button"
                  onClick={onSubmitRename}
                  className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                  style={{
                    background: 'var(--color-accent)',
                    color: 'var(--color-bubble-user-text)',
                  }}
                  title="保存 (Enter)"
                >
                  ✓ 保存
                </button>
                <button
                  type="button"
                  onClick={onCancelRename}
                  className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                  style={{
                    background: 'var(--color-bg-elevated)',
                    color: 'var(--color-text-secondary)',
                  }}
                  title="取消 (Esc)"
                >
                  取消
                </button>
              </>
            ) : (
              <>
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
                {canRename && (
                  <button
                    type="button"
                    onClick={onStartRename}
                    className="text-[10px] px-1 py-0.5 rounded hover:opacity-70 shrink-0"
                    style={{ color: 'var(--color-text-secondary)' }}
                    title="为此 voice 自定义名称"
                  >
                    ✏️ 重命名
                  </button>
                )}
              </>
            )}
          </div>
          <div className="text-[11px] truncate"
            style={{ color: 'var(--color-text-secondary)' }}
            title={voiceId}>
            {sub}
          </div>
          {usage && usage.length > 0 && (
            <div className="text-[10px] mt-0.5 truncate"
              style={{ color: 'var(--color-text-accent)' }}
              title={usage.map((c) => c.name).join(', ')}>
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
          {playing ? '⏸' : '▶'}
        </button>
      </div>
      {noteText && (
        <div className="text-[10px]"
          style={{ color: 'var(--color-text-secondary)' }}>
          {noteText}
        </div>
      )}
    </li>
  );
}


// ---------------------------------------------------------------------------
// 2026-06-06 · GsvTTSCard + FishTTSCard
// 跟 CosyVoiceTTSCard 同款 layout(标题 + 状态徽标 + 只读字段 + 操作)·
// 数据走 GET /api/tts/providers(共用 registry)· 不动 DB ai_providers ·
// 不碰 CosyVoice 流。绑定到角色仍走 CharacterPanel 的 VoicePicker
// (voice_model JSON per-character)· 本卡仅暴露 provider × model 元信息
// + 连通性 / 凭证状态。
// ---------------------------------------------------------------------------

interface ProviderTreeModel {
  id: string;
  label: string;
  tts_language?: string;
  // gsv-only:
  server_url?: string;
  default_emotion?: string;
  gpt_weights?: string;
  sovits_weights?: string;
  emotion_bank_dir?: string;
  // fish-only:
  fish_latency?: string;
}

interface ProviderTreeProvider {
  id: string;
  label: string;
  models: ProviderTreeModel[];
}

interface ProviderTreeResponse {
  providers: ProviderTreeProvider[];
}

// 2026-06-07 · 共用可折叠外壳 · 以 CosyVoiceTTSCard 的卡片外观为基准
// (rounded-lg p-4 + bg-surface 60% + border-subtle + header flex layout)。
// 三 TTS 卡(Cosy/GSV/Fish)共用 · 默认收起 · header 点击 toggle · body 条件渲染。
//
// statusBadge / headerActions 是 Fragment 容器 · 调用方塞任意 React 节点。
// header 用 div role=button 而非 <button> 是因为 headerActions 内可能含 button
// (CosyVoice「配置 Qwen 凭证」/「刷新复刻列表」),嵌套 <button> 是 invalid HTML。
function TtsCardShell({
  icon: Icon, title, statusBadge, headerActions, children, defaultExpanded = false,
}: {
  icon: LucideIcon;
  title: string;
  statusBadge?: React.ReactNode;
  headerActions?: React.ReactNode;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const toggle = () => setExpanded((e) => !e);
  return (
    <div className="rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggle();
          }
        }}
        className="flex items-center justify-between flex-wrap gap-2 cursor-pointer select-none"
        style={{ marginBottom: expanded ? '0.75rem' : 0 }}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <Icon size={16} style={{ color: 'var(--color-text-accent)' }} />
          <span className="text-sm font-medium truncate"
            style={{ color: 'var(--color-text-primary)' }}>
            {title}
          </span>
          {statusBadge}
        </div>
        <div
          className="flex items-center gap-2 shrink-0"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          {headerActions}
          <button
            type="button"
            onClick={toggle}
            className="rounded p-0.5 transition"
            style={{ color: 'var(--color-text-secondary)' }}
            aria-label={expanded ? '收起' : '展开'}
          >
            <ChevronDown
              size={16}
              style={{
                transform: expanded ? 'rotate(180deg)' : 'none',
                transition: 'transform 150ms ease',
              }}
            />
          </button>
        </div>
      </div>
      {expanded && children}
    </div>
  );
}

// label 走 muted uppercase 跟 CosyVoice body 的 section h5 同款字号字重 ·
// value 走 primary 强调 · mono 给 URL / 路径类(server)开启,人话值不开启。
// 2026-06-07 · 加 chip 盒子(rounded-md px-3 py-2 + bg-input + border-subtle)
// 照搬 CosyVoice TtsGalleryRow 的 per-item 容器 token(line 1556-1561 同源) ·
// 每条 FieldRow 各自一盒,行间 space-y-1.5 由调用方维持。
function FieldRow({ label, value, mono = false }: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div
      className="rounded-md px-3 py-2 flex items-baseline gap-3"
      style={{
        background: 'var(--color-bg-input)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <span
        className="text-[11px] font-medium uppercase tracking-wide w-20 shrink-0"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {label}
      </span>
      <span
        className={mono ? 'text-xs font-mono break-all' : 'text-xs'}
        style={{ color: 'var(--color-text-primary)' }}
      >
        {value}
      </span>
    </div>
  );
}

// 复用 GET /api/tts/providers · 父 hook 跑一次 · 两卡共用 reference。
function useTtsProviderTree(): {
  tree: ProviderTreeResponse | null;
  err: string | null;
} {
  const [tree, setTree] = useState<ProviderTreeResponse | null>(null);
  const [err, setErr]   = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${_BACKEND_BASE}/api/tts/providers`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as ProviderTreeResponse;
        if (!cancelled) setTree(j);
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, []);
  return { tree, err };
}


// ---------- GsvTTSCard ----------

interface GsvPingResult {
  ok: boolean;
  latency_ms: number;
  status_code?: number;
  error?: string;
}

function GsvTTSCard() {
  // INV (2026-06-11) · 重做:
  //  - 卡顶 server_url 输入(全局 · 走 ai_providers · 复用 doPing 测连接)
  //  - model 列表 fetch /api/tts/models?provider=gsv(DB tts_models 表 · per-PM SPEC-LOCK)
  //    行副信息显 [default_emotion, tts_language](去掉 server_url · 已挪卡顶)
  //  - 每行 Edit / Delete + 顶部 [+ 添加 GSV 模型] → AddGsvModelModal
  //  - 折叠"情绪覆盖"section(per-model 切换 · GET /tts/gsv/models/{id}/emotion_coverage)
  const [models, setModels] = useState<TtsModel[]>([]);
  const [modelsErr, setModelsErr] = useState<string | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);

  const refreshModels = useCallback(async () => {
    setLoadingModels(true);
    try {
      const list = await listTtsModels('gsv');
      setModels(list);
      setModelsErr(null);
    } catch (e) {
      setModelsErr((e as Error).message);
    } finally {
      setLoadingModels(false);
    }
  }, []);
  useEffect(() => { void refreshModels(); }, [refreshModels]);

  // ---- Global server_url ----
  const [serverUrl, setServerUrl] = useState('');
  const [serverUrlSource, setServerUrlSource] = useState<'global' | 'default'>('default');
  const [serverUrlDirty, setServerUrlDirty] = useState(false);
  const [savingServerUrl, setSavingServerUrl] = useState(false);
  const [serverUrlMsg, setServerUrlMsg] = useState<string | null>(null);

  const loadServerUrl = useCallback(async () => {
    try {
      const v = await getGsvServerUrl();
      setServerUrl(v.server_url ?? '');
      setServerUrlSource(v.source);
      setServerUrlDirty(false);
    } catch (e) {
      setServerUrlMsg(`加载 server_url 失败:${(e as Error).message}`);
    }
  }, []);
  useEffect(() => { void loadServerUrl(); }, [loadServerUrl]);

  const saveServerUrl = async () => {
    setSavingServerUrl(true);
    setServerUrlMsg(null);
    try {
      const v = await setGsvServerUrl(serverUrl.trim() || null);
      setServerUrl(v.server_url ?? '');
      setServerUrlSource(v.source);
      setServerUrlDirty(false);
      setServerUrlMsg('✓ 已保存');
    } catch (e) {
      setServerUrlMsg(`✗ 保存失败:${(e as Error).message}`);
    } finally {
      setSavingServerUrl(false);
    }
  };

  // ---- Ping (复用 backend POST /api/tts/gsv/ping) ----
  const [pingingFor, setPingingFor] = useState<string | null>(null);
  const [pingResult, setPingResult] = useState<(GsvPingResult & { server_url: string }) | null>(null);

  const doPing = async (urlToPing: string) => {
    if (!urlToPing) return;
    setPingingFor(urlToPing);
    setPingResult(null);
    try {
      const r = await fetch(`${_BACKEND_BASE}/api/tts/gsv/ping`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_url: urlToPing }),
      });
      const j = (await r.json()) as GsvPingResult;
      setPingResult({ ...j, server_url: urlToPing });
    } catch (e) {
      setPingResult({
        ok: false, latency_ms: 0,
        error: (e as Error).message,
        server_url: urlToPing,
      });
    } finally {
      setPingingFor(null);
    }
  };

  // ---- Edit / Delete ----
  const [editing, setEditing] = useState<TtsModel | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<TtsModel | null>(null);
  const [deleteMsg, setDeleteMsg] = useState<string | null>(null);

  const doDelete = async () => {
    if (!confirmDelete) return;
    try {
      await deleteTtsModel(confirmDelete.id);
      setConfirmDelete(null);
      setDeleteMsg(`✓ 已删除 ${confirmDelete.label}`);
      await refreshModels();
    } catch (e) {
      setDeleteMsg(`✗ 删除失败:${(e as Error).message}`);
    }
  };

  // ---- Emotion coverage (per-model · 折叠 / 展开 一个模型一次) ----
  const [coverageFor, setCoverageFor] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<EmotionCoverage | null>(null);
  const [coverageErr, setCoverageErr] = useState<string | null>(null);
  const [loadingCoverage, setLoadingCoverage] = useState(false);

  const toggleCoverage = async (modelId: string) => {
    if (coverageFor === modelId) {
      setCoverageFor(null);
      setCoverage(null);
      setCoverageErr(null);
      return;
    }
    setCoverageFor(modelId);
    setLoadingCoverage(true);
    setCoverageErr(null);
    setCoverage(null);
    try {
      const c = await getEmotionCoverage(modelId);
      setCoverage(c);
    } catch (e) {
      setCoverageErr((e as Error).message);
    } finally {
      setLoadingCoverage(false);
    }
  };

  const statusBadge = (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0"
      style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-secondary)' }}
    >
      self-hosted
    </span>
  );

  const inputStyle = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  } as const;

  return (
    <TtsCardShell icon={Server} title="GPT-SoVITS(ja)" statusBadge={statusBadge}>
      {/* ---- 卡顶:全局 server_url ---- */}
      <div className="rounded-md px-3 py-2 mb-3 flex flex-col gap-1.5"
        style={{ background: 'var(--color-bg-input)', border: '1px solid var(--color-border-subtle)' }}>
        <div className="text-[11px] font-medium uppercase tracking-wide"
          style={{ color: 'var(--color-text-secondary)' }}>
          全局 Server URL ({serverUrlSource === 'global' ? '已配置' : '回落默认'})
        </div>
        <div className="flex gap-1.5 items-center">
          <input
            className="flex-1 rounded-md px-2 py-1.5 text-xs font-mono"
            style={inputStyle}
            value={serverUrl}
            onChange={(e) => { setServerUrl(e.target.value); setServerUrlDirty(true); setServerUrlMsg(null); }}
            placeholder="http://192.168.x.x:9880"
          />
          <button
            type="button"
            onClick={() => void saveServerUrl()}
            disabled={!serverUrlDirty || savingServerUrl}
            className="text-xs px-2.5 py-1.5 rounded transition disabled:opacity-50 shrink-0"
            style={{ background: 'var(--color-accent)', color: 'var(--color-bubble-user-text)' }}
          >
            {savingServerUrl ? '…' : '保存'}
          </button>
          <button
            type="button"
            onClick={() => void doPing(serverUrl.trim())}
            disabled={!serverUrl.trim() || pingingFor === serverUrl.trim()}
            className="text-xs px-2.5 py-1.5 rounded transition disabled:opacity-50 shrink-0"
            style={inputStyle}
          >
            {pingingFor === serverUrl.trim() ? '…' : '测试连接'}
          </button>
        </div>
        {(serverUrlMsg || (pingResult && pingResult.server_url === serverUrl.trim())) && (
          <div className="text-[10px]" style={{
            color:
              pingResult && pingResult.server_url === serverUrl.trim()
                ? (pingResult.ok ? 'rgb(34,197,94)' : 'rgb(239,68,68)')
                : 'var(--color-text-secondary)',
          }}>
            {pingResult && pingResult.server_url === serverUrl.trim()
              ? (pingResult.ok
                ? `✓ 通 (${pingResult.latency_ms}ms${pingResult.status_code ? ` · HTTP ${pingResult.status_code}` : ''})`
                : `✗ 不通:${pingResult.error ?? '?'}`)
              : serverUrlMsg}
          </div>
        )}
      </div>

      {/* ---- model 行列表 ---- */}
      {modelsErr ? (
        <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          加载失败:{modelsErr}
        </p>
      ) : models.length === 0 && !loadingModels ? (
        <p className="text-xs mb-3" style={{ color: 'var(--color-text-secondary)' }}>
          还没注册 GSV 模型。点下方 [+ 添加 GSV 模型] 创建一个。
        </p>
      ) : (
        <ul className="space-y-1.5 mb-3">
          {models.map((m) => {
            const subParts = [
              m.default_emotion ? `默认 ${m.default_emotion}` : null,
              m.tts_language,
            ].filter(Boolean);
            const coverageOpen = coverageFor === m.model_id;
            return (
              <li
                key={m.id}
                className="rounded-md px-3 py-2 flex flex-col gap-1"
                style={{
                  background: 'var(--color-bg-input)',
                  border: '1px solid var(--color-border-subtle)',
                }}
              >
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void toggleCoverage(m.model_id)}
                    className="rounded p-0.5 shrink-0"
                    style={{ color: 'var(--color-text-secondary)' }}
                    title={coverageOpen ? '收起情绪覆盖' : '展开情绪覆盖'}
                  >
                    {coverageOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate"
                      style={{ color: 'var(--color-text-primary)' }}>
                      {m.label}
                      {m.builtin && (
                        <span className="text-[10px] ml-1.5 px-1 py-0.5 rounded uppercase"
                          style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-secondary)' }}>
                          builtin
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] truncate"
                      style={{ color: 'var(--color-text-secondary)' }}
                      title={subParts.join(' · ')}>
                      {subParts.join(' · ') || '—'}
                    </div>
                  </div>
                  <button
                    type="button" onClick={() => setEditing(m)}
                    className="rounded p-1 shrink-0"
                    style={{ color: 'var(--color-text-secondary)' }}
                    title="编辑"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button" onClick={() => { setConfirmDelete(m); setDeleteMsg(null); }}
                    className="rounded p-1 shrink-0"
                    style={{ color: 'var(--color-text-secondary)' }}
                    title="删除"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>

                {coverageOpen && (
                  <div className="mt-1 pl-5">
                    {loadingCoverage ? (
                      <div className="text-[10px]" style={{ color: 'var(--color-text-secondary)' }}>加载中…</div>
                    ) : coverageErr ? (
                      <div className="text-[10px]" style={{ color: 'rgb(239,68,68)' }}>
                        ✗ {coverageErr}
                      </div>
                    ) : coverage ? (
                      <div className="text-[10px]" style={{ color: 'var(--color-text-secondary)' }}>
                        <div className="mb-1">
                          lab_dir: <span className="font-mono">{coverage.lab_dir ?? '<未配置>'}</span>
                          {' · '}
                          default_emotion: <span className="font-mono">{coverage.default_emotion ?? '—'}</span>{' '}
                          {coverage.default_present
                            ? <span style={{ color: 'rgb(34,197,94)' }}>✓ 就位</span>
                            : <span style={{ color: 'rgb(239,68,68)' }}>✗ 缺失</span>}
                        </div>
                        {coverage.emotions.length === 0 ? (
                          <div>暂无 .lab(lab_dir 不存在 / 0 个 .lab 文件)</div>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {coverage.emotions.map((emo) => (
                              <span key={emo.name}
                                className="px-1.5 py-0.5 rounded font-mono"
                                title={emo.lab_preview ?? ''}
                                style={{
                                  background: 'var(--color-bg-elevated)',
                                  color: 'var(--color-text-primary)',
                                }}>
                                {emo.name}{emo.lab_size ? ` (${emo.lab_size}B)` : ''}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : null}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* ---- 添加 model ---- */}
      <div className="flex gap-2 items-center">
        <button
          type="button" onClick={() => setAddOpen(true)}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition"
          style={inputStyle}
        >
          <Plus size={14} /> 添加 GSV 模型
        </button>
        {deleteMsg && (
          <span className="text-[10px]"
            style={{ color: deleteMsg.startsWith('✓') ? 'rgb(34,197,94)' : 'rgb(239,68,68)' }}>
            {deleteMsg}
          </span>
        )}
      </div>

      {confirmDelete && (
        <div className="mt-2 rounded-md px-3 py-2 text-[11px]"
          style={{ background: 'var(--color-bg-input)', border: '1px solid var(--color-border)' }}>
          确认删除「{confirmDelete.label}」吗?{confirmDelete.builtin && '(builtin · 删了不复活)'}
          <div className="flex gap-2 mt-1.5">
            <button type="button" onClick={() => setConfirmDelete(null)}
              className="text-xs px-2 py-1 rounded"
              style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}>
              取消
            </button>
            <button type="button" onClick={() => void doDelete()}
              className="text-xs px-2 py-1 rounded"
              style={{ background: 'rgb(239,68,68)', color: '#fff' }}>
              确认删除
            </button>
          </div>
        </div>
      )}

      <p className="text-[10px] mt-2"
        style={{ color: 'var(--color-text-secondary)' }}>
        在 ⚙ 设置 → 角色管理 给单个角色选用 GSV 音色。
      </p>

      {(addOpen || editing) && (
        <AddGsvModelModal
          editing={editing}
          onClose={() => { setAddOpen(false); setEditing(null); }}
          onSaved={() => {
            setAddOpen(false);
            setEditing(null);
            void refreshModels();
          }}
          showToast={(t) => setDeleteMsg(t)}
        />
      )}
    </TtsCardShell>
  );
}


// ---------- FishTTSCard ----------

interface FishKeyStatus {
  configured: boolean;
  source: string | null;
}

function FishTTSCard() {
  const { tree, err: treeErr } = useTtsProviderTree();
  const fishProvider = tree?.providers.find((p) => p.id === 'fish') ?? null;
  const models = fishProvider?.models ?? [];

  const [keyStatus, setKeyStatus] = useState<FishKeyStatus | null>(null);
  const [keyErr, setKeyErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${_BACKEND_BASE}/api/tts/fish/key_status`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as FishKeyStatus;
        if (!cancelled) setKeyStatus(j);
      } catch (e) {
        if (!cancelled) setKeyErr((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 静态分类徽标(未就绪 / 待配置)· 跟 Cosy/GSV 同款 layout · 内容固定。
  // 动态 key 状态(✓ env / ⚠ 未配)留 body 顶部 alert 显示,见下方。
  const statusBadge = (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0"
      style={{
        background: 'var(--color-bg-elevated)',
        color: 'var(--color-text-secondary)',
      }}
    >
      未就绪 / 待配置
    </span>
  );

  return (
    <TtsCardShell icon={Cloud} title="Fish Audio(cloud · zh/ja)" statusBadge={statusBadge}>
      {treeErr ? (
        <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          加载失败:{treeErr}
        </p>
      ) : !fishProvider ? (
        <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          还没注册 Fish 模型。
        </p>
      ) : (
        <>
          {/* 2026-06-07 · per-model 行列表 · 跟 GSV / CosyVoice 同款 chip 结构 ·
              右侧动作:key 状态徽标(动态)取代原顶部 alert + select。 */}
          <ul className="space-y-1.5 mb-3">
            {models.map((m) => {
              const subParts = [
                'cloud',
                'reference upload',
                m.tts_language,
                m.fish_latency,
              ].filter(Boolean);
              return (
                <li
                  key={m.id}
                  className="rounded-md px-3 py-2 flex items-center gap-3"
                  style={{
                    background: 'var(--color-bg-input)',
                    border: '1px solid var(--color-border-subtle)',
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate"
                      style={{ color: 'var(--color-text-primary)' }}>
                      {m.label}
                    </div>
                    <div className="text-[10px] truncate"
                      style={{ color: 'var(--color-text-secondary)' }}
                      title={subParts.join(' · ')}>
                      {subParts.join(' · ') || '—'}
                    </div>
                  </div>
                  {/* key 徽标 · 状态 ✓ 已配 / ⚠ 未就绪 / 检查中… */}
                  {keyStatus === null ? (
                    <span className="text-[11px] shrink-0"
                      style={{ color: 'var(--color-text-secondary)' }}>
                      检查中…
                    </span>
                  ) : keyStatus.configured ? (
                    <span
                      className="text-[11px] inline-flex items-center gap-1 shrink-0"
                      style={{ color: 'rgb(34, 197, 94)' }}
                      title={`来源:${keyStatus.source}`}
                    >
                      <CheckCircle2 size={12} /> 已配
                    </span>
                  ) : (
                    <span
                      className="text-[11px] inline-flex items-center gap-1 shrink-0"
                      style={{ color: 'rgb(245, 158, 11)' }}
                      title="设 env FISH_API_KEY 后 restart backend"
                    >
                      <AlertTriangle size={12} /> 未就绪
                    </span>
                  )}
                </li>
              );
            })}
          </ul>

          {keyErr && (
            <p className="text-[11px] mb-2" style={{ color: 'rgb(239, 68, 68)' }}>
              凭证状态拉取失败:{keyErr}
            </p>
          )}

          <p className="text-[10px]"
            style={{ color: 'var(--color-text-secondary)' }}>
            用前先在环境变量里设好 <span className="font-mono">FISH_API_KEY</span>
            (dev 也可放 repo 根 <span className="font-mono">api_key.txt</span>),
            然后启动后端。
          </p>
        </>
      )}
    </TtsCardShell>
  );
}

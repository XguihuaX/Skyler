import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  KeyRound,
  Plus,
  Trash2,
} from 'lucide-react';
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
      ) : tab === 'asr' && vendorGroups.every((v) => v.providers.length === 0) && ungrouped.length === 0 ? (
        // bugfix-3.2 过渡期:ASR provider 列表为空, 但保留 VAD / Whisper
        // 现有控件可用。3.3 ship 后 ASR provider 才入 DB。
        <div className="space-y-4">
          <div
            className="text-xs px-3 py-2 rounded"
            style={{
              background: 'color-mix(in srgb, var(--color-accent) 8%, transparent)',
              color: 'var(--color-text-secondary)',
              border: '1px dashed var(--color-border-subtle)',
            }}
          >
            ASR Provider 管理将在 Bugfix-3.3 推出。当前 VAD / 静音超时
            等控件保留在下方,可继续使用。
          </div>
          <AsrVadSection />
        </div>
      ) : tab === 'tts' && vendorGroups.every((v) => v.providers.length === 0) && ungrouped.length === 0 ? (
        <div className="space-y-4">
          <div
            className="text-xs px-3 py-2 rounded"
            style={{
              background: 'color-mix(in srgb, var(--color-accent) 8%, transparent)',
              color: 'var(--color-text-secondary)',
              border: '1px dashed var(--color-border-subtle)',
            }}
          >
            TTS Provider 管理将在 Bugfix-3.3 推出。当前 TTS 总开关保留
            在下方,角色音色仍在 ⚙ 设置 → 角色管理 内编辑。
          </div>
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

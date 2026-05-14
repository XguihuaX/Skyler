import { useState } from 'react';
import {
  type AIVendor,
  type ProviderType,
  createProvider,
  createVendor,
} from '../../lib/ai_providers';

/**
 * bugfix-3.2: 新增 provider modal。
 *
 * 两种模式:
 *   - 选 builtin vendor → 只填 name / model / endpoint (可空, 用 vendor 默认)
 *   - 选 "+ 新建自定义 vendor" → inline 表单填 vendor 字段 + provider 字段
 *
 * 提交流程:
 *   1. 新 vendor 模式 → POST /api/ai-vendors → 拿到 vendor_id
 *   2. POST /api/ai-providers (vendor_id 是上一步的, 或选 builtin 时直接)
 *   3. parent onSaved 回调刷新列表
 *
 * 新建后未配凭证 → onSaved 时 toast 提示用户去 vendor card 配凭证。
 *
 * 校验:
 *   - vendor id 必须 ^[a-z0-9_-]+$ (与 backend 一致)
 *   - name / model 必填非空
 *   - extra_json 若填必须是合法 JSON
 */

interface AddProviderFormProps {
  type: ProviderType;
  vendors: AIVendor[];
  onClose: () => void;
  onSaved: (created: { providerId: number; vendorId: string | null; vendorIsNew: boolean }) => void;
  showToast: (text: string) => void;
}

const VENDOR_ID_RE = /^[a-z0-9_-]+$/;

export default function AddProviderForm({
  type,
  vendors,
  onClose,
  onSaved,
  showToast,
}: AddProviderFormProps) {
  // Vendor selection: 一个 builtin/custom id 或字面量 "__new__"
  const [vendorMode, setVendorMode] = useState<'existing' | 'new' | 'none'>(
    vendors.length > 0 ? 'existing' : 'new',
  );
  const [vendorId, setVendorId] = useState<string>(vendors[0]?.id ?? '');

  // 新 vendor 字段
  const [newVendorId, setNewVendorId] = useState('');
  const [newVendorName, setNewVendorName] = useState('');
  const [newVendorEndpoint, setNewVendorEndpoint] = useState('');
  const [newVendorKeyName, setNewVendorKeyName] = useState('');

  // Provider 字段
  const [name, setName] = useState('');
  const [model, setModel] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [extraJson, setExtraJson] = useState('');

  const [submitting, setSubmitting] = useState(false);

  const selectedVendor = vendors.find((v) => v.id === vendorId) ?? null;

  const onSubmit = async () => {
    // Validate
    if (!name.trim()) {
      showToast('Provider 名称必填');
      return;
    }
    if (!model.trim()) {
      showToast('Model 必填');
      return;
    }
    if (extraJson.trim()) {
      try {
        JSON.parse(extraJson);
      } catch {
        showToast('Extra JSON 格式错误');
        return;
      }
    }

    let resolvedVendorId: string | null = null;
    let vendorIsNew = false;

    if (vendorMode === 'new') {
      if (!VENDOR_ID_RE.test(newVendorId)) {
        showToast('Vendor ID 必须由小写字母 / 数字 / - / _ 组成,3-32 字符');
        return;
      }
      if (newVendorId.length < 3 || newVendorId.length > 32) {
        showToast('Vendor ID 长度 3-32');
        return;
      }
      if (!newVendorName.trim() || !newVendorKeyName.trim()) {
        showToast('新 Vendor 的 名称 + 凭证环境变量名 必填');
        return;
      }
      resolvedVendorId = newVendorId;
      vendorIsNew = true;
    } else if (vendorMode === 'existing') {
      resolvedVendorId = vendorId || null;
    } // 'none' → vendor_id 留 null (eg ASR 单 provider 不绑 vendor)

    setSubmitting(true);
    try {
      if (vendorIsNew) {
        await createVendor({
          id: newVendorId,
          name: newVendorName,
          default_endpoint: newVendorEndpoint || null,
          credential_key_name: newVendorKeyName,
        });
      }
      const created = await createProvider({
        vendor_id: resolvedVendorId,
        type,
        name: name.trim(),
        model: model.trim(),
        endpoint: endpoint.trim() || null,
        extra_json: extraJson.trim() || null,
      });
      showToast(`已添加 ${created.name}`);
      onSaved({
        providerId: created.id,
        vendorId: resolvedVendorId,
        vendorIsNew,
      });
    } catch (e) {
      showToast(`添加失败：${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  } as const;

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[480px] max-h-[90vh] overflow-y-auto shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h4
          className="text-sm font-semibold mb-1"
          style={{ color: 'var(--color-text-primary)' }}
        >
          新增 {type.toUpperCase()} Provider
        </h4>
        <p
          className="text-xs mb-4"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          选已有 Vendor 或新建一个。新建 Vendor 后保存即创建,
          但凭证 (API Key) 需在 Vendor 卡片上另行配置。
        </p>

        {/* Vendor selection */}
        <div className="mb-3">
          <label
            className="block text-xs mb-1"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Vendor
          </label>
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <button
              type="button"
              onClick={() => setVendorMode('existing')}
              disabled={vendors.length === 0}
              className="text-[11px] px-2 py-1 rounded"
              style={{
                background: vendorMode === 'existing'
                  ? 'var(--color-accent)'
                  : 'var(--color-bg-input)',
                color: vendorMode === 'existing'
                  ? 'var(--color-bubble-user-text)'
                  : 'var(--color-text-primary)',
                opacity: vendors.length === 0 ? 0.5 : 1,
              }}
            >
              选已有
            </button>
            <button
              type="button"
              onClick={() => setVendorMode('new')}
              className="text-[11px] px-2 py-1 rounded"
              style={{
                background: vendorMode === 'new'
                  ? 'var(--color-accent)'
                  : 'var(--color-bg-input)',
                color: vendorMode === 'new'
                  ? 'var(--color-bubble-user-text)'
                  : 'var(--color-text-primary)',
              }}
            >
              + 新建自定义 Vendor
            </button>
            {type !== 'llm' && (
              <button
                type="button"
                onClick={() => setVendorMode('none')}
                className="text-[11px] px-2 py-1 rounded"
                style={{
                  background: vendorMode === 'none'
                    ? 'var(--color-accent)'
                    : 'var(--color-bg-input)',
                  color: vendorMode === 'none'
                    ? 'var(--color-bubble-user-text)'
                    : 'var(--color-text-primary)',
                }}
              >
                不绑 Vendor
              </button>
            )}
          </div>

          {vendorMode === 'existing' && (
            <select
              value={vendorId}
              onChange={(e) => setVendorId(e.target.value)}
              className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
              style={inputStyle}
            >
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.vendor_kind}{v.has_credential ? ' ✓' : ''})
                </option>
              ))}
            </select>
          )}

          {vendorMode === 'new' && (
            <div className="space-y-2 mt-1 p-3 rounded-md"
              style={{ background: 'var(--color-bg-input)' }}>
              <div>
                <label className="block text-[11px] mb-0.5"
                  style={{ color: 'var(--color-text-secondary)' }}>
                  Vendor ID(URL-safe: 小写字母 / 数字 / - / _)
                </label>
                <input
                  type="text" value={newVendorId}
                  onChange={(e) => setNewVendorId(e.target.value)}
                  placeholder="my-vllm"
                  className="w-full rounded-md px-2 py-1 text-sm font-mono"
                  style={inputStyle}
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="block text-[11px] mb-0.5"
                  style={{ color: 'var(--color-text-secondary)' }}>
                  显示名称
                </label>
                <input
                  type="text" value={newVendorName}
                  onChange={(e) => setNewVendorName(e.target.value)}
                  placeholder="My vLLM"
                  className="w-full rounded-md px-2 py-1 text-sm"
                  style={inputStyle}
                />
              </div>
              <div>
                <label className="block text-[11px] mb-0.5"
                  style={{ color: 'var(--color-text-secondary)' }}>
                  默认 Endpoint(provider 可覆盖)
                </label>
                <input
                  type="text" value={newVendorEndpoint}
                  onChange={(e) => setNewVendorEndpoint(e.target.value)}
                  placeholder="http://localhost:8000/v1"
                  className="w-full rounded-md px-2 py-1 text-sm font-mono"
                  style={inputStyle}
                />
              </div>
              <div>
                <label className="block text-[11px] mb-0.5"
                  style={{ color: 'var(--color-text-secondary)' }}>
                  凭证环境变量名(.env fallback)
                </label>
                <input
                  type="text" value={newVendorKeyName}
                  onChange={(e) => setNewVendorKeyName(e.target.value)}
                  placeholder="MY_VLLM_API_KEY"
                  className="w-full rounded-md px-2 py-1 text-sm font-mono"
                  style={inputStyle}
                  autoComplete="off"
                />
              </div>
            </div>
          )}
        </div>

        {/* Provider fields */}
        <div className="space-y-2 mb-3">
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Provider 显示名称
            </label>
            <input
              type="text" value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="GPT-4o (我的 fork)"
              className="w-full rounded-md px-2 py-1.5 text-sm"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Model ID(传给 LiteLLM)
            </label>
            <input
              type="text" value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="openai/gpt-4o-mini"
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono"
              style={inputStyle}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Endpoint
              <span className="ml-1 text-[10px]"
                style={{ color: 'var(--color-text-secondary)' }}>
                空时用 Vendor 默认
                {selectedVendor?.default_endpoint &&
                  ` (${selectedVendor.default_endpoint})`}
              </span>
            </label>
            <input
              type="text" value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder=""
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Extra Config(JSON,可选)
            </label>
            <textarea
              value={extraJson}
              onChange={(e) => setExtraJson(e.target.value)}
              placeholder='{"temperature": 0.7}'
              rows={2}
              className="w-full rounded-md px-2 py-1.5 text-xs font-mono resize-none"
              style={inputStyle}
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void onSubmit()}
            disabled={submitting}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            {submitting ? '添加中…' : '添加'}
          </button>
        </div>
      </div>
    </div>
  );
}

import { useState } from 'react';
import {
  type AIVendor,
  type ProviderType,
  createProvider,
} from '../../lib/ai_providers';

/**
 * bugfix-3.2.8: 在某个 vendor 下添加 model。
 *
 * 跟 AddVendorModal 概念分开 —— 此 modal 是"在已有 vendor 卡片下加 model 行"。
 *
 * 3 个字段:
 *   - Provider display name (必填) —— 用户起的名 (eg "GPT-5 Turbo")
 *   - Model identifier (必填) —— LiteLLM 用的 model 名, **无需带前缀**;
 *     backend 按 vendor.id 自动 prepend (qwen/openai → openai/, anthropic →
 *     anthropic/, deepseek → deepseek/, custom vendor → 原样)
 *   - Endpoint (可选) —— 留空用 vendor.default_endpoint
 *
 * 不提供 model 下拉预设 (用户拍板:模型迭代太快, 写死预设会落伍)。
 */

interface AddModelModalProps {
  vendor: AIVendor;
  type: ProviderType;  // 一般是 'llm'
  onClose: () => void;
  onSaved: () => void;
  showToast: (text: string) => void;
}

export default function AddModelModal({
  vendor,
  type,
  onClose,
  onSaved,
  showToast,
}: AddModelModalProps) {
  const [name, setName] = useState('');
  const [model, setModel] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const isCustomVendor = vendor.vendor_kind === 'custom';

  const onSubmit = async () => {
    if (!name.trim()) {
      showToast('Provider 显示名称必填');
      return;
    }
    if (!model.trim()) {
      showToast('Model identifier 必填');
      return;
    }
    setSubmitting(true);
    try {
      const created = await createProvider({
        vendor_id: vendor.id,
        type,
        name: name.trim(),
        model: model.trim(),
        endpoint: endpoint.trim() || null,
      });
      showToast(`已添加 ${created.name}`);
      onSaved();
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
        className="rounded-lg p-5 w-[460px] max-h-[90vh] overflow-y-auto shadow-2xl"
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
          添加 {vendor.name} 模型
        </h4>
        <p
          className="text-xs mb-4"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          填模型显示名 + LiteLLM 的 model 标识。
          {isCustomVendor
            ? '自定义 Vendor — 模型名按你自己 protocol 填,系统不加前缀。'
            : '系统会按 Vendor 自动加 LiteLLM 前缀,你填 raw 名即可。'}
        </p>

        <div className="space-y-3 mb-4">
          {/* Vendor name (readonly display) */}
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-secondary)' }}>
              Vendor
            </label>
            <div
              className="rounded-md px-2 py-1.5 text-sm flex items-center gap-2"
              style={{
                background: 'var(--color-bg-input)',
                border: '1px solid var(--color-border-subtle)',
                color: 'var(--color-text-primary)',
              }}
            >
              <span
                className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                style={{ background: vendor.color ?? 'var(--color-text-secondary)' }}
              />
              {vendor.name}
              <span
                className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide"
                style={{
                  background: 'var(--color-bg-elevated)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                {vendor.vendor_kind}
              </span>
            </div>
          </div>

          {/* Provider display name */}
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Provider 显示名称 <span style={{ color: 'rgb(244,63,94)' }}>*</span>
            </label>
            <input
              type="text" value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="GPT-5 Turbo / Claude Opus 5"
              className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
              style={inputStyle}
              autoFocus
            />
            <div className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)' }}>
              你起的名,显示在 provider 列表里
            </div>
          </div>

          {/* Model identifier */}
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Model identifier <span style={{ color: 'rgb(244,63,94)' }}>*</span>
            </label>
            <input
              type="text" value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={
                vendor.id === 'qwen' ? 'qwen3.6-flash'
                : vendor.id === 'openai' ? 'gpt-5-turbo-2026-04'
                : vendor.id === 'anthropic' ? 'claude-opus-5'
                : vendor.id === 'deepseek' ? 'deepseek-reasoner'
                : 'your-model-id'
              }
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono focus:outline-none"
              style={inputStyle}
              autoComplete="off"
              spellCheck={false}
            />
            <div className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)' }}>
              {isCustomVendor
                ? '自定义 vendor 不加前缀, 按 LiteLLM 文档填 (eg "openai/your-model")'
                : '请填 model 名(无需带 provider 前缀,系统会自动添加)'}
            </div>
            <div className="text-[10px] mt-0.5"
              style={{ color: 'var(--color-text-secondary)' }}>
              示例: gpt-4o / claude-sonnet-4-6 / deepseek-chat
            </div>
          </div>

          {/* Endpoint (optional) */}
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Endpoint (可选)
            </label>
            <input
              type="text" value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder=""
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono focus:outline-none"
              style={inputStyle}
              autoComplete="off"
            />
            <div className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)' }}>
              留空用 Vendor 默认
              {vendor.default_endpoint && ` (${vendor.default_endpoint})`}
            </div>
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

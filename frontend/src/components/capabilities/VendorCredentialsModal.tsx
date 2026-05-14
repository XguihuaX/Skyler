import { useState } from 'react';
import { CheckCircle2, Eye, EyeOff, Trash2 } from 'lucide-react';
import {
  type AIVendor,
  clearVendorCredentials,
  setVendorCredentials,
} from '../../lib/ai_providers';

/**
 * bugfix-3.2: Vendor 凭证 modal — fixed-overlay 形态, 复用 MCP CredentialsModal
 * pattern。语义级别从 server-level (mcp) 提到 vendor-level (AI Providers),
 * 一个 vendor 一组凭证, 多 model 共享。
 *
 * 字段:
 *   - API Key (password input + show/hide 切换)
 *   - 环境变量名 (builtin 只读, custom 可编辑)
 *
 * 已有凭证:显示 ✓ 状态 + [删除凭证] 按钮; 空 input 留空保持不变,
 * 输入新值则覆盖。删除凭证不影响 vendor 本身。
 *
 * .env fallback hint:builtin vendor 即使 DB 无凭证, 若 .env 配了
 * `credential_key_name` 对应的环境变量, dispatcher 也能用 —— UI 这里不能
 * 直接知道 .env 状态, 只展示 `has_credential` (DB) 状态 + 提示文案。
 */

interface VendorCredentialsModalProps {
  vendor: AIVendor;
  onClose: () => void;
  onSaved: () => void;
  showToast: (text: string) => void;
}

export default function VendorCredentialsModal({
  vendor,
  onClose,
  onSaved,
  showToast,
}: VendorCredentialsModalProps) {
  const [keyValue, setKeyValue] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const isBuiltin = vendor.vendor_kind === 'builtin';
  const alreadyConfigured = vendor.has_credential;

  const onSave = async () => {
    if (!keyValue.trim()) {
      showToast('请输入 API Key');
      return;
    }
    setSubmitting(true);
    try {
      await setVendorCredentials(vendor.id, keyValue);
      showToast(`${vendor.name} 凭证已保存`);
      onSaved();
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const onClear = async () => {
    if (!alreadyConfigured) return;
    setSubmitting(true);
    try {
      await clearVendorCredentials(vendor.id);
      showToast(`${vendor.name} 凭证已删除`);
      onSaved();
    } catch (e) {
      showToast(`删除失败：${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[420px] shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h4
          className="text-sm font-semibold mb-1 flex items-center gap-2"
          style={{ color: 'var(--color-text-primary)' }}
        >
          <span
            className="inline-block w-3 h-3 rounded-full"
            style={{ background: vendor.color ?? 'var(--color-text-secondary)' }}
          />
          配置 {vendor.name} 凭证
        </h4>
        <p
          className="text-xs mb-4"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          API Key 以 Fernet 加密存入本地 SQLite。
          {alreadyConfigured && ' 当前已配置 ✓ ;留空不会覆盖现有值。'}
          {!alreadyConfigured && isBuiltin && (
            ` 若环境变量 ${vendor.credential_key_name} 已设, 也会被自动使用。`
          )}
        </p>

        <div className="space-y-3">
          <div>
            <label
              className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}
            >
              环境变量名(凭证 key)
              {isBuiltin && (
                <span
                  className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded uppercase"
                  style={{
                    background: 'var(--color-bg-elevated)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  builtin · 只读
                </span>
              )}
            </label>
            <input
              type="text"
              value={vendor.credential_key_name}
              disabled
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono opacity-70"
              style={{
                background: 'var(--color-bg-input)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            />
          </div>

          <div>
            <label
              className="flex items-center gap-1 text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}
            >
              API Key
              {alreadyConfigured && (
                <CheckCircle2 size={12} style={{ color: 'var(--color-accent)' }} />
              )}
            </label>
            <div className="relative">
              <input
                type={showSecret ? 'text' : 'password'}
                value={keyValue}
                onChange={(e) => setKeyValue(e.target.value)}
                placeholder={
                  alreadyConfigured ? '已配置(留空保持不变)' : '粘贴你的 API Key'
                }
                className="w-full rounded-md px-2 py-1.5 pr-9 text-sm focus:outline-none"
                style={{
                  background: 'var(--color-bg-input)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={() => setShowSecret((v) => !v)}
                className="absolute right-1 top-1/2 -translate-y-1/2 p-1.5 rounded hover:bg-[var(--color-bg-elevated)]"
                style={{ color: 'var(--color-text-secondary)' }}
                title={showSecret ? '隐藏' : '显示'}
              >
                {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between pt-4">
          {alreadyConfigured ? (
            <button
              type="button"
              onClick={() => void onClear()}
              disabled={submitting}
              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md transition disabled:opacity-50"
              style={{ color: 'rgb(244,63,94)' }}
            >
              <Trash2 size={12} /> 删除凭证
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
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
              onClick={() => void onSave()}
              disabled={submitting || !keyValue.trim()}
              className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-bubble-user-text)',
              }}
            >
              {submitting ? '保存中…' : alreadyConfigured ? '更新' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

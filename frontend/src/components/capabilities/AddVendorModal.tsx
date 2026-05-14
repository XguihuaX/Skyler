import { useState } from 'react';
import {
  createVendor,
  setVendorCredentials,
} from '../../lib/ai_providers';

/**
 * bugfix-3.2.8: 添加自定义 Vendor。
 *
 * 跟 AddModelModal 概念分开 —— 此 modal 是顶层"加一个新厂商"。
 * 创建后立即可用(本 modal 也收凭证 value, 串接 POST credentials)。
 *
 * 字段(必填):
 *   - Vendor ID (URL-safe ^[a-z0-9_-]+$, 3-32 char)
 *   - Vendor name (显示用)
 *   - Default endpoint (eg http://localhost:8000/v1)
 *   - Credential env var name (eg MY_VLLM_KEY) —— .env fallback 路径
 *   - Credential value (eg sk-xxx) —— 立即写库 (Fernet 加密)
 *
 * 提交流程:
 *   1. POST /api/ai-vendors
 *   2. POST /api/ai-vendors/{id}/credentials
 *   3. onSaved 触发 refresh
 *
 * 创建后 vendor 卡片下没 model,用户点 [+ 添加 X 模型] 自填(走 AddModelModal,
 * custom vendor 模式提示"自定义 vendor 不加前缀")。
 */

interface AddVendorModalProps {
  onClose: () => void;
  onSaved: () => void;
  showToast: (text: string) => void;
}

const VENDOR_ID_RE = /^[a-z0-9_-]+$/;

export default function AddVendorModal({
  onClose,
  onSaved,
  showToast,
}: AddVendorModalProps) {
  const [vendorId, setVendorId] = useState('');
  const [vendorName, setVendorName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [keyName, setKeyName] = useState('');
  const [keyValue, setKeyValue] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async () => {
    if (!VENDOR_ID_RE.test(vendorId)) {
      showToast('Vendor ID 必须由小写字母/数字/-/_ 组成');
      return;
    }
    if (vendorId.length < 3 || vendorId.length > 32) {
      showToast('Vendor ID 长度 3-32 字符');
      return;
    }
    if (!vendorName.trim()) {
      showToast('Vendor 名称必填');
      return;
    }
    if (!endpoint.trim()) {
      showToast('默认 Endpoint 必填');
      return;
    }
    if (!keyName.trim()) {
      showToast('凭证环境变量名必填');
      return;
    }
    if (!keyValue.trim()) {
      showToast('凭证 Value 必填(立即写库,Fernet 加密)');
      return;
    }
    setSubmitting(true);
    try {
      await createVendor({
        id: vendorId,
        name: vendorName.trim(),
        default_endpoint: endpoint.trim(),
        credential_key_name: keyName.trim(),
      });
      await setVendorCredentials(vendorId, keyValue.trim());
      showToast(`已添加 Vendor ${vendorName}`);
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
          添加自定义 Vendor
        </h4>
        <p
          className="text-xs mb-4"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          填厂商信息 + API Key 一步搞定。Key 用 Fernet 加密存本地 SQLite。
        </p>

        <div className="space-y-3 mb-4">
          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              Vendor ID <span style={{ color: 'rgb(244,63,94)' }}>*</span>
            </label>
            <input
              type="text" value={vendorId}
              onChange={(e) => setVendorId(e.target.value)}
              placeholder="my-vllm"
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono focus:outline-none"
              style={inputStyle}
              autoComplete="off"
              autoFocus
            />
            <div className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)' }}>
              URL-safe: 小写字母 / 数字 / - / _, 3-32 字符
            </div>
          </div>

          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              显示名称 <span style={{ color: 'rgb(244,63,94)' }}>*</span>
            </label>
            <input
              type="text" value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
              placeholder="My vLLM"
              className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
              style={inputStyle}
            />
          </div>

          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              默认 Endpoint <span style={{ color: 'rgb(244,63,94)' }}>*</span>
            </label>
            <input
              type="text" value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="http://localhost:8000/v1"
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono focus:outline-none"
              style={inputStyle}
              autoComplete="off"
            />
          </div>

          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              凭证环境变量名 <span style={{ color: 'rgb(244,63,94)' }}>*</span>
            </label>
            <input
              type="text" value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              placeholder="MY_VLLM_API_KEY"
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono focus:outline-none"
              style={inputStyle}
              autoComplete="off"
            />
            <div className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)' }}>
              .env fallback 路径名(DB 凭证清空时可由 .env 顶上)
            </div>
          </div>

          <div>
            <label className="block text-xs mb-1"
              style={{ color: 'var(--color-text-primary)' }}>
              凭证 Value <span style={{ color: 'rgb(244,63,94)' }}>*</span>
            </label>
            <input
              type="password" value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              placeholder="sk-xxxxxxxxxxx"
              className="w-full rounded-md px-2 py-1.5 text-sm font-mono focus:outline-none"
              style={inputStyle}
              autoComplete="off"
              spellCheck={false}
            />
            <div className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)' }}>
              立即写库,Fernet 加密存本地 SQLite
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

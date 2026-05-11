/**
 * v3.5 chunk 9 Part 2 — SettingsPanel [用户画像] section。
 *
 * 显示 ``users.profile_summary``，提供：
 *  - 只读卡片 + 字数（实际/可建议 500 字）
 *  - [手动编辑] modal：textarea 可编辑，保存调 PATCH
 *  - [清空] 二次确认 → DELETE
 *  - [立刻重新生成] loading → 同步 POST /regenerate 返回新内容
 *
 * 后端 endpoints 见 backend/routes/users_api.py。
 * profile_summary 为 NULL 时显示"尚未生成画像（对话满 50 轮后自动生成）"，
 * [立刻重新生成] 仍可点（min_user_rows=1 在 endpoint 路径，少量对话也能预览）。
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Edit3, Trash2 } from 'lucide-react';
import {
  fetchUserProfile,
  patchProfileSummary,
  deleteProfileSummary,
  regenerateProfileSummary,
  type UserProfile,
} from '../lib/profile';

interface Props {
  userId: string;
  showToast: (text: string) => void;
}

export default function UserProfileSection({ userId, showToast }: Props) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await fetchUserProfile(userId);
      setProfile(p);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const summary = profile?.profile_summary ?? null;
  const charCount = summary?.length ?? 0;

  const onRegenerate = async () => {
    setRegenerating(true);
    try {
      const r = await regenerateProfileSummary(userId);
      if (r.status === 'regenerated') {
        showToast(`画像已重新生成（${(r.profile_summary || '').length} 字）`);
      } else {
        showToast(r.detail || `跳过：${r.status}`);
      }
      await refresh();
    } catch (e) {
      showToast(`重新生成失败：${(e as Error).message}`);
    } finally {
      setRegenerating(false);
    }
  };

  const onConfirmClear = async () => {
    setConfirmClear(false);
    try {
      await deleteProfileSummary(userId);
      showToast('画像已清空');
      await refresh();
    } catch (e) {
      showToast(`清空失败：${(e as Error).message}`);
    }
  };

  return (
    <>
      <section className="mb-4">
        <h3
          className="text-sm font-semibold mb-2"
          style={{ color: 'var(--color-text-primary)' }}
        >
          用户画像
        </h3>
        <div
          className="rounded-md px-3 py-2"
          style={{
            background: 'var(--color-bg-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <p
            className="text-[11px] mb-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            Momo 对你的整体感觉（每 50 轮对话自动更新；用户消息为输入源）
          </p>

          {loading && !profile && (
            <div className="text-xs py-2" style={{ color: 'var(--color-text-secondary)' }}>
              加载中…
            </div>
          )}
          {error && (
            <div className="text-xs py-2 text-rose-300">
              加载失败：{error}
            </div>
          )}

          {!loading && !error && (
            <div
              className="text-xs rounded p-2 max-h-40 overflow-y-auto whitespace-pre-wrap"
              style={{
                background: 'var(--color-bg-elevated)',
                color: summary
                  ? 'var(--color-text-primary)'
                  : 'var(--color-text-secondary)',
                border: '1px solid var(--color-border-subtle)',
              }}
            >
              {summary || '尚未生成画像（对话满 50 轮后自动生成；可点[立刻重新生成]立即预览）'}
            </div>
          )}

          <div
            className="text-[10px] mt-1 flex justify-between"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <span>字数：{charCount} / 500</span>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
              style={{ color: 'var(--color-text-secondary)' }}
              title="重新拉取当前 profile"
            >
              <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>

          <div className="flex gap-2 mt-2">
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={loading}
              className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <Edit3 size={11} />
              手动编辑
            </button>
            <button
              type="button"
              onClick={() => setConfirmClear(true)}
              disabled={loading || !summary}
              className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <Trash2 size={11} />
              清空
            </button>
            <button
              type="button"
              onClick={() => void onRegenerate()}
              disabled={loading || regenerating}
              className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
              title="同步触发 LLM 基于最新对话重算"
            >
              <RefreshCw
                size={11}
                className={regenerating ? 'animate-spin' : ''}
              />
              {regenerating ? '生成中…' : '立刻重新生成'}
            </button>
          </div>
        </div>
      </section>

      {editing && (
        <EditModal
          initial={summary || ''}
          onClose={() => setEditing(false)}
          onSave={async (text) => {
            try {
              await patchProfileSummary(userId, text);
              showToast('画像已保存');
              setEditing(false);
              await refresh();
            } catch (e) {
              showToast(`保存失败：${(e as Error).message}`);
            }
          }}
        />
      )}

      {confirmClear && (
        <ConfirmModal
          text={'确认清空当前画像？\n下次自动重写时会基于最新对话从零生成。'}
          onCancel={() => setConfirmClear(false)}
          onConfirm={() => void onConfirmClear()}
        />
      )}
    </>
  );
}


// ---------------------------------------------------------------------------
// Edit modal
// ---------------------------------------------------------------------------


function EditModal({
  initial,
  onClose,
  onSave,
}: {
  initial: string;
  onClose: () => void;
  onSave: (text: string) => Promise<void>;
}) {
  const [text, setText] = useState(initial);
  const [saving, setSaving] = useState(false);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[480px] shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h4
          className="text-sm font-semibold mb-3"
          style={{ color: 'var(--color-text-primary)' }}
        >
          手动编辑用户画像
        </h4>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={10}
          className="w-full text-xs rounded p-2 resize-none"
          style={{
            background: 'var(--color-bg-elevated)',
            color: 'var(--color-text-primary)',
            border: '1px solid var(--color-border)',
            outline: 'none',
          }}
          placeholder="输入对该用户的描述..."
        />
        <div
          className="text-[10px] mt-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          字数：{text.length} / 500
        </div>
        <div className="flex justify-end gap-2 mt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-md"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave(text);
              } finally {
                setSaving(false);
              }
            }}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bg-base)',
            }}
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Confirm modal (与 MemoryManagerDrawer 同 spirit，但用 rose-600 危险色)
// ---------------------------------------------------------------------------


function ConfirmModal({
  text,
  onConfirm,
  onCancel,
}: {
  text: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
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
            className="px-3 py-1.5 text-xs rounded-md"
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
            className="px-3 py-1.5 text-xs rounded-md bg-rose-600 text-white hover:bg-rose-500"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}

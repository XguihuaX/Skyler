import { useCallback, useEffect, useMemo, useState } from 'react';
import { Trash2, X } from 'lucide-react';

const BACKEND_BASE = 'http://127.0.0.1:8000';

type MemoryType = 'fact' | 'instruction' | 'emotion' | 'activity' | 'daily';
type FilterValue = 'all' | MemoryType;

const TYPE_OPTIONS: { value: FilterValue; label: string }[] = [
  { value: 'all',         label: '全部' },
  { value: 'fact',        label: '事实 (fact)' },
  { value: 'instruction', label: '偏好 (instruction)' },
  { value: 'emotion',     label: '情绪 (emotion)' },
  { value: 'activity',    label: '活动 (activity)' },
  { value: 'daily',       label: '日常 (daily)' },
];

interface MemoryRow {
  id: number;
  content: string;
  type: string;
  created_at: string | null;
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

interface Props {
  open: boolean;
  userId: string;
  characterId: number | null;
  onClose: () => void;
  onCountChange?: (count: number) => void;
}

/**
 * Right-side slide-in drawer for managing the long-term memory list.
 *
 * - Always mounted; opening/closing toggles translate-x for the same slide
 *   animation as ChatHistoryDrawer.
 * - pt-10 keeps the header below TopBar (z-50) so the drawer × never
 *   overlaps the global app-close button.
 * - Type filter is purely client-side (useMemo) — backend always returns the
 *   full active list and we slice locally to keep counts in sync after edits
 *   without re-firing the request.
 */
export default function MemoryManagerDrawer({
  open,
  userId,
  characterId,
  onClose,
  onCountChange,
}: Props) {
  const [memories, setMemories] = useState<MemoryRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterValue>('all');
  const [pendingDelete, setPendingDelete] = useState<MemoryRow | null>(null);
  const [pendingClearAll, setPendingClearAll] = useState(false);

  const fetchMemories = useCallback(async () => {
    setLoading(true);
    setErrorText(null);
    try {
      const params = new URLSearchParams({ user_id: userId });
      if (characterId !== null) params.set('character_id', String(characterId));
      const url = `${BACKEND_BASE}/api/memory/list?${params.toString()}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as MemoryRow[];
      setMemories(data);
      onCountChange?.(data.length);
    } catch (e) {
      console.error('[MemoryManagerDrawer] fetch failed:', e);
      setErrorText(`记忆列表加载失败：${(e as Error).message}`);
      setMemories([]);
      onCountChange?.(0);
    } finally {
      setLoading(false);
    }
  }, [userId, characterId, onCountChange]);

  // Refetch each time the drawer opens; gives the user the latest snapshot
  // even after a chat turn that just saved a memory.
  useEffect(() => {
    if (!open) return;
    void fetchMemories();
  }, [open, fetchMemories]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const filtered = useMemo(() => {
    if (!memories) return [];
    if (filter === 'all') return memories;
    return memories.filter((m) => m.type === filter);
  }, [memories, filter]);

  const deleteOne = async (id: number) => {
    try {
      const r = await fetch(`${BACKEND_BASE}/api/memory/${id}`, { method: 'DELETE' });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      await fetchMemories();
    } catch (e) {
      console.error('[MemoryManagerDrawer] delete failed:', e);
      setErrorText(`删除失败：${(e as Error).message}`);
    }
  };

  const clearAll = async () => {
    if (!memories || memories.length === 0) return;
    try {
      await Promise.all(
        memories.map((m) =>
          fetch(`${BACKEND_BASE}/api/memory/${m.id}`, { method: 'DELETE' }),
        ),
      );
      await fetchMemories();
    } catch (e) {
      console.error('[MemoryManagerDrawer] clear-all failed:', e);
      setErrorText(`清空失败：${(e as Error).message}`);
    }
  };

  return (
    <div
      className={`fixed inset-0 z-40 ${open ? '' : 'pointer-events-none'}`}
      aria-hidden={!open}
    >
      {/* Click-outside catcher (left blank area) */}
      <div
        className={`absolute inset-0 right-[60%] transition-opacity duration-300 ${
          open ? 'opacity-100' : 'opacity-0'
        }`}
        onClick={onClose}
        aria-label="关闭记忆管理"
      />

      {/* Drawer panel */}
      <div
        className={`absolute top-0 right-0 h-full w-[60%]
                    backdrop-blur-lg shadow-2xl pt-10
                    transition-transform duration-300 ease-out
                    flex flex-col
                    ${open ? 'translate-x-0' : 'translate-x-full'}`}
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 85%, transparent)',
          borderLeft: '1px solid var(--color-border-subtle)',
        }}
      >
        {/* Header */}
        <div
          className="h-12 px-4 flex items-center justify-between shrink-0"
          style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
        >
          <h3
            className="text-sm font-medium"
            style={{ color: 'var(--color-text-primary)' }}
          >
            记忆管理
          </h3>
          <button
            type="button"
            className="w-8 h-8 rounded-md flex items-center justify-center transition hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_60%,transparent)]"
            style={{ color: 'var(--color-text-secondary)' }}
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>

        {/* Filter row */}
        <div
          className="px-4 py-3 shrink-0 flex items-center gap-2"
          style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
        >
          <label
            className="text-xs"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            筛选
          </label>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as FilterValue)}
            className="rounded-md px-2 py-1 text-xs focus:outline-none"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            {TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <span
            className="ml-auto text-xs"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            共 {filtered.length} 条
            {filter !== 'all' && memories ? ` / ${memories.length}` : ''}
          </span>
        </div>

        {/* Scrollable list */}
        <div className="flex-1 overflow-y-auto px-4 py-2">
          {loading && memories === null ? (
            <p
              className="text-xs py-4 text-center"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              加载中…
            </p>
          ) : errorText ? (
            <p className="text-rose-300 text-xs py-4">{errorText}</p>
          ) : filtered.length === 0 ? (
            <p
              className="text-xs py-6 text-center"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {memories && memories.length === 0
                ? '还没有记忆，对话中聊到值得记的事会自动保存'
                : '当前筛选下没有记忆'}
            </p>
          ) : (
            <ul
              className="divide-y"
              style={{ borderColor: 'var(--color-border-subtle)' }}
            >
              {filtered.map((m) => (
                <li
                  key={m.id}
                  className="py-3 flex items-start gap-3"
                  style={{ borderColor: 'var(--color-border-subtle)' }}
                >
                  <div className="flex-1 min-w-0">
                    <p
                      className="text-sm break-words"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      {m.content}
                    </p>
                    <div className="flex items-center gap-2 mt-1.5">
                      <span
                        className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded"
                        style={{
                          background: 'var(--color-bg-elevated)',
                          color: 'var(--color-text-secondary)',
                        }}
                      >
                        {m.type}
                      </span>
                      <span
                        className="text-xs"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        {m.created_at ?? ''}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setPendingDelete(m)}
                    className="shrink-0 px-2 py-1 rounded-md text-rose-300 hover:bg-rose-700/30 transition flex items-center justify-center"
                    title="删除这条记忆"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div
          className="px-4 py-3 shrink-0 flex justify-center"
          style={{ borderTop: '1px solid var(--color-border-subtle)' }}
        >
          <button
            type="button"
            onClick={() => setPendingClearAll(true)}
            disabled={!memories || memories.length === 0}
            className="px-4 py-1.5 text-xs rounded-md bg-rose-600/80 text-white hover:bg-rose-500 transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            全部清空
          </button>
        </div>
      </div>

      {pendingDelete && (
        <ConfirmModal
          text={`确认删除这条记忆？\n\n${pendingDelete.content}`}
          onConfirm={async () => {
            const id = pendingDelete.id;
            setPendingDelete(null);
            await deleteOne(id);
          }}
          onCancel={() => setPendingDelete(null)}
        />
      )}

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
    </div>
  );
}

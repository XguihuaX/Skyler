import { useCallback, useEffect, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { useAppStore } from '../store';
import {
  createConversation,
  deleteConversation,
  fetchConversations,
  fetchMessages,
  patchConversation,
  type ConversationRow,
} from '../lib/config';

const NEW_CONVERSATION_TITLE = '新对话';

export default function ConversationList() {
  const userId = useAppStore((s) => s.defaultUserId);
  const conversations = useAppStore((s) => s.conversations);
  const setConversations = useAppStore((s) => s.setConversations);
  const upsertConversation = useAppStore((s) => s.upsertConversation);
  const removeConversationFromStore = useAppStore((s) => s.removeConversation);
  const currentConversationId = useAppStore((s) => s.currentConversationId);
  const setCurrentConversationId = useAppStore((s) => s.setCurrentConversationId);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const setChatMessages = useAppStore((s) => s.setChatMessages);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ConversationRow | null>(null);
  const [deleting, setDeleting] = useState(false);

  const reload = useCallback(async () => {
    if (!userId) return;
    try {
      const rows = await fetchConversations(userId, currentCharacterId ?? undefined);
      setConversations(rows);
      // V2.5-C2c — if the previously selected conversation belongs to a
      // different character (or was deleted upstream), drop the active
      // selection and clear the in-memory chatMessages so the chat area
      // doesn't keep displaying stale turns.
      const activeId = useAppStore.getState().currentConversationId;
      if (activeId !== null && !rows.some((c) => c.id === activeId)) {
        useAppStore.getState().setCurrentConversationId(null);
        useAppStore.getState().setChatMessages([]);
      }
    } catch (e) {
      console.error('[ConversationList] reload failed:', e);
    }
  }, [userId, currentCharacterId, setConversations]);

  useEffect(() => {
    reload();
  }, [reload]);

  const loadMessages = useCallback(async (conversationId: number) => {
    try {
      const rows = await fetchMessages(conversationId);
      setChatMessages(rows.map((r) => ({
        id: `s-${r.id}`,
        role: r.role,
        content: r.content,
        streaming: false,
        ts: 0,
        kind: r.kind ?? 'normal',
      })));
    } catch (e) {
      console.error('[ConversationList] fetchMessages failed:', e);
      setChatMessages([]);
    }
  }, [setChatMessages]);

  const handleSelect = async (id: number) => {
    if (id === currentConversationId) return;
    setCurrentConversationId(id);
    await loadMessages(id);
  };

  const handleCreate = async () => {
    if (!userId || !currentCharacterId) {
      console.warn('[ConversationList] cannot create: userId/character not ready');
      return;
    }
    try {
      const created = await createConversation(userId, currentCharacterId, NEW_CONVERSATION_TITLE);
      upsertConversation(created);
      setCurrentConversationId(created.id);
      setChatMessages([]);
    } catch (e) {
      console.error('[ConversationList] create failed:', e);
    }
  };

  const startEdit = (c: ConversationRow) => {
    setEditingId(c.id);
    setEditingTitle(c.title);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditingTitle('');
  };

  const commitEdit = async () => {
    if (editingId === null) return;
    const trimmed = editingTitle.trim();
    if (!trimmed) {
      cancelEdit();
      return;
    }
    try {
      const updated = await patchConversation(editingId, { title: trimmed });
      upsertConversation(updated);
    } catch (e) {
      console.error('[ConversationList] rename failed:', e);
    } finally {
      cancelEdit();
    }
  };

  const requestDelete = (c: ConversationRow) => {
    setDeleteTarget(c);
  };

  const cancelDelete = () => {
    if (deleting) return;
    setDeleteTarget(null);
  };

  const confirmDelete = async () => {
    const target = deleteTarget;
    if (!target) return;
    setDeleting(true);
    try {
      await deleteConversation(target.id);
      removeConversationFromStore(target.id);
      // If we just deleted the active conversation, fall back to the first remaining one.
      if (currentConversationId === target.id) {
        const remaining = useAppStore.getState().conversations;
        if (remaining.length > 0) {
          const next = remaining[0];
          setCurrentConversationId(next.id);
          await loadMessages(next.id);
        } else {
          setCurrentConversationId(null);
          setChatMessages([]);
        }
      }
      setDeleteTarget(null);
    } catch (e) {
      console.error('[ConversationList] delete failed:', e);
    } finally {
      setDeleting(false);
    }
  };

  const collapsed = useAppStore((s) => s.conversationListCollapsed);

  return (
    <div
      className={`shrink-0 h-full flex flex-col overflow-hidden transition-[width] duration-200 ease-out ${
        collapsed ? 'w-0' : 'w-60'
      }`}
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        borderRight: collapsed ? 'none' : '1px solid var(--color-border-subtle)',
      }}
    >
      <div
        className="px-3 py-3 shrink-0"
        style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
      >
        <button
          type="button"
          className="w-full px-3 py-1.5 text-sm rounded-md transition flex items-center justify-center gap-1.5"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-bubble-user-text)',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-hover)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-accent)')}
          onClick={handleCreate}
          title="新建对话"
        >
          <Plus size={16} />
          <span>新对话</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <div
            className="text-sm px-3 py-4 text-center"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            还没有对话
          </div>
        ) : (
          <ul className="py-1">
            {conversations.map((c) => {
              const isActive = c.id === currentConversationId;
              const isEditing = c.id === editingId;
              return (
                <li
                  key={c.id}
                  className="group relative px-3 py-2 cursor-pointer transition-colors text-sm"
                  style={
                    isActive
                      ? {
                          background: 'color-mix(in srgb, var(--color-accent) 30%, transparent)',
                          color: 'var(--color-text-primary)',
                        }
                      : { color: 'var(--color-text-primary)' }
                  }
                  onClick={() => !isEditing && handleSelect(c.id)}
                  onMouseEnter={(e) => {
                    setHoveredId(c.id);
                    if (!isActive) {
                      e.currentTarget.style.background =
                        'color-mix(in srgb, var(--color-bg-elevated) 60%, transparent)';
                    }
                  }}
                  onMouseLeave={(e) => {
                    setHoveredId((cur) => (cur === c.id ? null : cur));
                    if (!isActive) e.currentTarget.style.background = 'transparent';
                  }}
                  onDoubleClick={(e) => {
                    e.stopPropagation();
                    startEdit(c);
                  }}
                >
                  {isEditing ? (
                    <input
                      autoFocus
                      type="text"
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      onBlur={commitEdit}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          void commitEdit();
                        } else if (e.key === 'Escape') {
                          e.preventDefault();
                          cancelEdit();
                        }
                      }}
                      className="w-full text-sm rounded px-2 py-0.5 outline-none"
                      style={{
                        background: 'var(--color-bg-input)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-primary)',
                      }}
                    />
                  ) : (
                    <>
                      <div className="truncate pr-6">{c.title}</div>
                      <div
                        className="text-xs mt-0.5 truncate pr-6"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        {c.message_count} 条 · {c.updated_at ?? ''}
                      </div>
                      {hoveredId === c.id && (
                        <button
                          type="button"
                          title="删除对话"
                          className="absolute top-1.5 right-1.5 w-6 h-6 rounded text-rose-400 hover:bg-rose-500/20 hover:text-rose-300 flex items-center justify-center transition"
                          onClick={(e) => {
                            e.stopPropagation();
                            requestDelete(c);
                          }}
                        >
                          <X size={14} />
                        </button>
                      )}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {deleteTarget !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm"
          style={{ background: 'color-mix(in srgb, var(--color-bg-base) 50%, transparent)' }}
        >
          <div
            className="w-[380px] rounded-xl p-5 shadow-2xl"
            style={{
              background: 'var(--color-bg-surface)',
              border: '1px solid var(--color-border)',
            }}
          >
            <h4
              className="text-base font-medium mb-2"
              style={{ color: 'var(--color-text-primary)' }}
            >
              确认删除这个对话？
            </h4>
            <p
              className="text-sm mb-4 break-words line-clamp-3"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {deleteTarget.title} · {deleteTarget.message_count} 条消息将一并删除
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="px-3 py-1.5 text-sm transition"
                style={{
                  color: deleting ? 'var(--color-text-secondary)' : 'var(--color-text-primary)',
                }}
                onClick={cancelDelete}
                disabled={deleting}
              >
                取消
              </button>
              <button
                type="button"
                className="px-3 py-1.5 text-sm rounded-md bg-rose-600 hover:bg-rose-500 text-white disabled:opacity-50"
                onClick={confirmDelete}
                disabled={deleting}
              >
                {deleting ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

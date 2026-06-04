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
        proactiveTrigger: r.proactive_trigger ?? undefined,
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
  const setCollapsed = useAppStore((s) => s.setConversationListCollapsed);

  // 防御:collapsed=true 时 return null · Panel.tsx 在外层已经条件渲染
  // 浮卡 vs chip · 这里再 guard 一次让 ConvList 单独使用也安全。
  // 必须在所有 hooks 之后(已是最后一行 hook · React rules-of-hooks 允许)。
  if (collapsed) return null;

  return (
    <div
      className="absolute flex flex-col overflow-hidden"
      style={{
        // 2026-06-03 · Round 3.4 · ConvList chip 化 · 镜像右侧 ChatHistoryPanel:
        // 从 flex 流 240×全高列 → absolute 浮卡(top:20 left:80 bottom:100 width:280)
        // left:80 跟 Sidebar dock 让位的 paddingLeft 对齐 · bottom:100 给输入丸留位 ·
        // 圆角 + glass + shadow-card-lift 浮起感 · 跟暖巷视觉对称。
        top: '20px',
        left: '80px',
        bottom: '100px',
        width: '280px',
        borderRadius: 'var(--glass-radius)',
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
        border: 'var(--glass-border)',
        boxShadow: 'var(--glass-shadow)',
        zIndex: 20,
      }}
    >
      <div className="px-3 py-3 shrink-0 flex items-center gap-2">
        <button
          type="button"
          className="flex-1 px-3 py-1.5 text-sm rounded-md transition flex items-center justify-center gap-1.5"
          style={{
            // 2026-06-03 · 新对话按钮 100% accent 实色 → 65% 半透 + blur ·
            // 让壁纸从按钮后面透出 · 仍保留 accent tint 让按钮辨识度在
            background: 'color-mix(in srgb, var(--color-accent) 65%, transparent)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            color: 'var(--color-bubble-user-text)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 50%, transparent)',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'color-mix(in srgb, var(--color-accent-hover) 75%, transparent)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'color-mix(in srgb, var(--color-accent) 65%, transparent)')}
          onClick={handleCreate}
          title="新建对话"
        >
          <Plus size={16} />
          <span>新对话</span>
        </button>
        {/* Round 3.4 · 收起按钮 · 跟 ChatHistoryPanel 顶部 X 对称 */}
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="p-1 rounded hover:opacity-80 transition"
          style={{ color: 'var(--glass-text-muted)' }}
          title="收起对话列表"
          aria-label="收起对话列表"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <div
            className="text-sm px-3 py-4 text-center"
            style={{ color: 'var(--glass-text-muted)' }}
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
                          color: 'var(--glass-text)',
                          textShadow: 'var(--glass-text-shadow)',
                        }
                      : {
                          color: 'var(--glass-text)',
                          textShadow: 'var(--glass-text-shadow)',
                        }
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

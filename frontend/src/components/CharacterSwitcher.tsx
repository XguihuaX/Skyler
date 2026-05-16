import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Circle, UserRound } from 'lucide-react';
import { useAppStore } from '../store';
import { useAppApi } from '../contexts/appApi';
import {
  fetchConversations,
  createConversation,
  fetchMessages,
} from '../lib/config';

/**
 * Compact character switcher placed in TopBar.
 *
 * 显示当前角色（头像 + 名字 + ▾），下拉列出所有角色；底部一行跳转到角色管理页。
 * v3-B 起角色管理是 Panel 的独立子视图（panelView='characters'），不再用 Drawer。
 *
 * Rule B(绑定语义)— 切角色时**前端必须做这一连串**:
 *   1. setCurrentCharacterId(new) — UI 立刻反映
 *   2. fetchConversations(uid, new) → 取该角色对话列表
 *   3. 有 → setCurrentConversationId(latest);无 → createConversation 新建
 *   4. sendCharacterSwitch(new, conv_id) — 告诉 backend 当前 UI 状态
 *      (backend ``ConnectionManager.set_current`` 收到后做为 proactive
 *       投递 gate 的 source of truth,不触发 LLM)
 * 这一套是 audit_binding_semantics.md 方案 3 的"根治闭环"。
 */
export default function CharacterSwitcher() {
  const characters         = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const setCurrentCharacterId = useAppStore((s) => s.setCurrentCharacterId);
  const setCurrentConversationId = useAppStore((s) => s.setCurrentConversationId);
  const setChatMessages    = useAppStore((s) => s.setChatMessages);
  const userId             = useAppStore((s) => s.defaultUserId);
  const setPanelView       = useAppStore((s) => s.setPanelView);
  const { sendCharacterSwitch } = useAppApi();

  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click / ESC
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const current = characters.find((c) => c.id === currentCharacterId) ?? null;

  const renderAvatar = (path: string | null, size: 'sm' | 'md') => {
    const dim = size === 'md' ? 'w-6 h-6' : 'w-5 h-5';
    const iconSize = size === 'md' ? 14 : 12;
    if (path) {
      return <img src={path} alt="" className={`${dim} rounded-full object-cover`} />;
    }
    return (
      <span
        className={`${dim} rounded-full flex items-center justify-center`}
        style={{
          background: 'var(--color-bg-elevated)',
          color: 'var(--color-text-secondary)',
        }}
      >
        <UserRound size={iconSize} />
      </span>
    );
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-2 py-1 rounded-md transition text-sm hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_70%,transparent)]"
        style={{ color: 'var(--color-text-primary)' }}
        title="切换角色"
      >
        {renderAvatar(current?.avatar_path ?? null, 'md')}
        <span className="max-w-[8rem] truncate">{current?.name ?? '未选择'}</span>
        <ChevronDown size={14} style={{ color: 'var(--color-text-secondary)' }} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-56 z-[60] rounded-lg shadow-2xl overflow-hidden"
          style={{
            background: 'var(--color-bg-elevated)',
            border: '1px solid var(--color-border)',
          }}
        >
          <ul className="max-h-72 overflow-y-auto py-1">
            {characters.length === 0 ? (
              <li
                className="px-3 py-2 text-xs"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                暂无角色
              </li>
            ) : (
              characters.map((c) => {
                const active = c.id === currentCharacterId;
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => {
                        if (active) {
                          setOpen(false);
                          return;
                        }
                        // Rule B 闭环 — 先切角色,异步切对话(latest or new),
                        // 然后 sendCharacterSwitch 让 backend snapshot 新 UI 状态。
                        setCurrentCharacterId(c.id);
                        setOpen(false);
                        (async () => {
                          let convId: number | null = null;
                          let isNewConv = false;
                          try {
                            const convs = await fetchConversations(userId, c.id);
                            if (convs.length > 0) {
                              convId = convs[0].id;
                            } else {
                              const created = await createConversation(
                                userId, c.id, '新对话',
                              );
                              convId = created.id;
                              isNewConv = true;
                            }
                            setCurrentConversationId(convId);
                          } catch (err) {
                            console.error(
                              '[CharacterSwitcher] resolve conversation failed',
                              err,
                            );
                            // 回退:留 conv=null,backend ``_resolve_conv_char``
                            // 兜底走最近 conv;set_current 仍发,至少 char 同步。
                          }
                          // 加载该 conversation 完整消息列表到 chatMessages
                          // — Galgame 中央右侧 ChatHistoryPanel 显示。
                          // 新建对话 / 无对话 → 空数组(ChatHistory 自带"开始
                          // 一段对话吧"空状态 + 引导)。
                          if (convId !== null && !isNewConv) {
                            try {
                              const msgs = await fetchMessages(convId);
                              setChatMessages(msgs.map((r) => ({
                                id: `s-${r.id}`,
                                role: r.role,
                                content: r.content,
                                streaming: false,
                                ts: 0,
                                kind: r.kind ?? 'normal',
                                proactiveTrigger: r.proactive_trigger ?? undefined,
                              })));
                            } catch (err) {
                              console.error(
                                '[CharacterSwitcher] fetchMessages failed',
                                err,
                              );
                              setChatMessages([]);
                            }
                          } else {
                            setChatMessages([]);
                          }
                          sendCharacterSwitch(c.id, convId);
                        })();
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm transition"
                      style={
                        active
                          ? {
                              background: 'color-mix(in srgb, var(--color-accent) 35%, transparent)',
                              color: 'var(--color-text-primary)',
                            }
                          : { color: 'var(--color-text-primary)' }
                      }
                      onMouseEnter={(e) => {
                        if (!active) {
                          e.currentTarget.style.background =
                            'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!active) e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      {renderAvatar(c.avatar_path, 'sm')}
                      <span className="flex-1 truncate text-left">{c.name}</span>
                      {active && (
                        <Circle
                          size={10}
                          fill="currentColor"
                          style={{ color: 'var(--color-text-accent)' }}
                        />
                      )}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
          <div style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setPanelView('characters');
              }}
              className="w-full px-3 py-2 text-sm transition text-left"
              style={{ color: 'var(--color-text-primary)' }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background =
                  'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)')
              }
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              管理角色…
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

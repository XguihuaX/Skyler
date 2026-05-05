import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '../store';
import {
  createCharacter,
  deleteCharacter,
  fetchBaseInstruction,
  fetchCharacters,
  patchCharacter,
  updateBaseInstruction,
  type CharacterRow,
} from '../lib/config';
import { fetchLive2DModels } from '../lib/live2d';

const DEFAULT_CHARACTER_NAME = 'Momo';
const PERSONA_PREVIEW_LEN = 30;

// ---------------------------------------------------------------------------
// 通用：确认弹窗 + Toast
// ---------------------------------------------------------------------------

interface ConfirmModalProps {
  text: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmModal({ text, onConfirm, onCancel }: ConfirmModalProps) {
  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
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

interface ToastInfo {
  id: number;
  text: string;
}

// ---------------------------------------------------------------------------
// 表单态
// ---------------------------------------------------------------------------

type FormMode = 'create' | 'edit';

interface FormState {
  mode: FormMode;
  id: number | null;          // 编辑目标 id；create 时为 null
  isMomo: boolean;            // Momo(id=1)：名字 disabled
  name: string;
  persona: string;
  voice_model: string;
  live2d_model: string;
  avatar_path: string;
}

const EMPTY_FORM: FormState = {
  mode: 'create',
  id: null,
  isMomo: false,
  name: '',
  persona: '',
  voice_model: '',
  live2d_model: '',
  avatar_path: '',
};

const PERSONA_PLACEHOLDER =
  '描述这个角色的性格、说话风格、背景设定等。\n例：\n你是一只傲娇的猫娘助理「小桃」。说话简短，带「喵～」语气词。\n擅长记住用户的事，遇到夸奖会害羞地否认。';

// ---------------------------------------------------------------------------
// 头像占位：取角色名首字符（汉字 / 英文均可），背景用 accent
// ---------------------------------------------------------------------------

function AvatarBubble({ name, path }: { name: string; path: string | null }) {
  if (path) {
    return (
      <img
        src={path}
        alt=""
        className="w-10 h-10 rounded-full object-cover shrink-0"
      />
    );
  }
  // 取首个 unicode 字符（避免 emoji / 多字节切半）
  const initial = Array.from(name.trim())[0]?.toUpperCase() ?? '?';
  return (
    <span
      className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-medium shrink-0"
      style={{
        background: 'var(--color-accent)',
        color: 'var(--color-bubble-user-text)',
      }}
    >
      {initial}
    </span>
  );
}

// ---------------------------------------------------------------------------
// v3-B 补丁: 通用设定区块（所有角色共享的输出风格约束）
// ---------------------------------------------------------------------------

interface BaseInstructionSectionProps {
  showToast: (text: string) => void;
}

function BaseInstructionSection({ showToast }: BaseInstructionSectionProps) {
  const [text, setText]       = useState('');
  const [loaded, setLoaded]   = useState(false);
  const [saving, setSaving]   = useState(false);
  // savedFlash: 保存成功后短暂出现的"已保存"提示
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const v = await fetchBaseInstruction();
        if (cancelled) return;
        setText(v);
        setLoaded(true);
      } catch (e) {
        console.error('[BaseInstructionSection] fetch failed:', e);
        showToast(`通用设定加载失败：${(e as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [showToast]);

  const onSave = async () => {
    setSaving(true);
    try {
      await updateBaseInstruction(text);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1800);
    } catch (e) {
      console.error('[BaseInstructionSection] save failed:', e);
      showToast(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="mb-4 rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <h3
        className="text-sm font-medium mb-2"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        通用设定
      </h3>
      <p
        className="text-[11px] mb-2"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        所有角色共享的输出风格约束，会拼到每个角色 persona 之前生效。
      </p>
      <textarea
        value={text}
        disabled={!loaded}
        onChange={(e) => setText(e.target.value)}
        placeholder="例：回复简短克制，不超过3句话；不复述用户说的话；像真实的人一样说话。"
        rows={6}
        className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none resize-y disabled:opacity-50"
        style={{
          background: 'var(--color-bg-input)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-primary)',
        }}
      />
      <div className="flex items-center justify-end gap-3 mt-2">
        {savedFlash && (
          <span
            className="text-xs"
            style={{ color: 'var(--color-text-accent)' }}
          >
            已保存
          </span>
        )}
        <button
          type="button"
          onClick={onSave}
          disabled={!loaded || saving}
          className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-bubble-user-text)',
          }}
        >
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// CharacterPanel — Sidebar 「角色」入口的主区视图
// ---------------------------------------------------------------------------

export default function CharacterPanel() {
  const setCharactersInStore  = useAppStore((s) => s.setCharacters);
  const currentCharacterId    = useAppStore((s) => s.currentCharacterId);
  const setCurrentCharacterId = useAppStore((s) => s.setCurrentCharacterId);

  // v3-E2 commit 3b：Live2D 模型扫描结果，下拉数据源。从 store 读，避免每次表单
  // 打开都重新扫描；mount 时拉一次，刷新按钮按需重拉。
  const live2dModels    = useAppStore((s) => s.live2dModels);
  const setLive2dModels = useAppStore((s) => s.setLive2dModels);

  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [loading, setLoading]       = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm]             = useState<FormState | null>(null); // null = 不显示表单
  const [pendingDelete, setPendingDelete] = useState<CharacterRow | null>(null);
  const [toasts, setToasts]         = useState<ToastInfo[]>([]);
  const [live2dLoading, setLive2dLoading] = useState(false);
  const [live2dError,   setLive2dError]   = useState<string | null>(null);

  const showToast = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3000);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await fetchCharacters();
      setCharacters(rows);
      setCharactersInStore(rows);
    } catch (e) {
      console.error('[CharacterPanel] fetch failed:', e);
      showToast(`角色加载失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [setCharactersInStore, showToast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // v3-E2 commit 3b：Live2D 模型列表加载 + 刷新按钮共享同一回调
  const refreshLive2D = useCallback(async () => {
    setLive2dLoading(true);
    setLive2dError(null);
    try {
      const data = await fetchLive2DModels();
      setLive2dModels(data.models);
    } catch (e) {
      const msg = (e as Error).message;
      console.error('[CharacterPanel] live2d models fetch failed:', e);
      setLive2dError(msg);
    } finally {
      setLive2dLoading(false);
    }
  }, [setLive2dModels]);

  useEffect(() => {
    void refreshLive2D();
  }, [refreshLive2D]);

  const startCreate = () => {
    setForm({ ...EMPTY_FORM, mode: 'create' });
  };

  const startEdit = (c: CharacterRow) => {
    setForm({
      mode: 'edit',
      id: c.id,
      isMomo: c.name === DEFAULT_CHARACTER_NAME,
      name: c.name,
      persona: c.persona,
      voice_model: c.voice_model ?? '',
      live2d_model: c.live2d_model ?? '',
      avatar_path: c.avatar_path ?? '',
    });
  };

  const cancelForm = () => setForm(null);

  const submitForm = async () => {
    if (!form) return;
    const name        = form.name.trim();
    const persona     = form.persona.trim();
    const voiceModel  = form.voice_model.trim();
    const live2dModel = form.live2d_model.trim();
    const avatarPath  = form.avatar_path.trim();
    if (!name || !persona) {
      showToast('角色名和提示词都是必填项');
      return;
    }
    setSubmitting(true);
    try {
      if (form.mode === 'create') {
        await createCharacter({
          name,
          persona,
          avatar_path: avatarPath || null,
          voice_model: voiceModel || null,
          live2d_model: live2dModel || null,
        });
      } else if (form.id !== null) {
        // Momo(id=1) 名字不可改 — 即使前端表单 disabled，这里也排除掉
        await patchCharacter(form.id, {
          ...(form.isMomo ? {} : { name }),
          persona,
          avatar_path: avatarPath || null,
          voice_model: voiceModel || null,
          live2d_model: live2dModel || null,
        });
      }
      await refresh();
      cancelForm();
    } catch (e) {
      console.error('[CharacterPanel] submit failed:', e);
      showToast(`保存失败：${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const confirmDelete = async () => {
    const target = pendingDelete;
    if (!target) return;
    setPendingDelete(null);
    try {
      await deleteCharacter(target.id);
      // 删掉的是当前角色 → 退回剩余里的第一个
      if (currentCharacterId === target.id) {
        const remaining = characters.filter((c) => c.id !== target.id);
        setCurrentCharacterId(remaining[0]?.id ?? null);
      }
      // 正在编辑的就是被删的 → 关掉表单
      if (form?.id === target.id) cancelForm();
      await refresh();
    } catch (e) {
      console.error('[CharacterPanel] delete failed:', e);
      const msg = (e as Error).message;
      if (msg.includes('cannot delete the default Momo')) {
        showToast('Momo 不可删除');
      } else {
        showToast(`删除失败：${msg}`);
      }
    }
  };

  const formValid = !!form && form.name.trim() && form.persona.trim();

  // -------------------------------------------------------------------------
  // 样式片段
  // -------------------------------------------------------------------------
  const inputStyle: React.CSSProperties = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 relative">
      {/* 顶部：标题 + 新建按钮 */}
      <div className="flex items-center justify-between mb-4">
        <h2
          className="text-base font-medium"
          style={{ color: 'var(--color-text-primary)' }}
        >
          角色管理
        </h2>
        <button
          type="button"
          onClick={startCreate}
          className="px-3 py-1.5 text-xs rounded-md transition flex items-center gap-1"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-bubble-user-text)',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-hover)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-accent)')}
        >
          <Plus size={16} />
          <span>新建角色</span>
        </button>
      </div>

      {/* v3-B 补丁: 通用设定（位于角色列表上方） */}
      <BaseInstructionSection showToast={showToast} />

      {/* 通用设定与角色列表之间的分割线 */}
      <div
        className="mb-4"
        style={{ borderTop: '1px solid var(--color-border-subtle)' }}
      />

      {/* 角色卡片列表 */}
      <section className="space-y-2 mb-4">
        {loading && characters.length === 0 ? (
          <p
            className="text-xs py-8 text-center"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            加载中…
          </p>
        ) : characters.length === 0 ? (
          <p
            className="text-xs py-8 text-center"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            暂无角色
          </p>
        ) : (
          characters.map((c) => {
            const isMomo  = c.name === DEFAULT_CHARACTER_NAME;
            const active  = c.id === currentCharacterId;
            const preview = c.persona.length > PERSONA_PREVIEW_LEN
              ? `${c.persona.slice(0, PERSONA_PREVIEW_LEN)}…`
              : c.persona;
            return (
              <div
                key={c.id}
                role="button"
                tabIndex={0}
                onClick={() => setCurrentCharacterId(c.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setCurrentCharacterId(c.id);
                  }
                }}
                className="rounded-lg p-3 flex items-center gap-3 cursor-pointer transition"
                style={{
                  background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
                  border: active
                    ? '1px solid var(--color-accent)'
                    : '1px solid var(--color-border-subtle)',
                }}
              >
                <AvatarBubble name={c.name} path={c.avatar_path} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className="text-sm font-medium truncate"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      {c.name}
                    </span>
                    {isMomo && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                        style={{
                          background:
                            'color-mix(in srgb, var(--color-accent) 60%, transparent)',
                          color: 'var(--color-text-primary)',
                        }}
                      >
                        默认
                      </span>
                    )}
                  </div>
                  <p
                    className="text-xs mt-0.5 truncate"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    {preview}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      startEdit(c);
                    }}
                    className="w-8 h-8 rounded-md flex items-center justify-center transition hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_60%,transparent)]"
                    style={{ color: 'var(--color-text-secondary)' }}
                    title="编辑"
                    aria-label="编辑"
                  >
                    <Pencil size={16} />
                  </button>
                  {!isMomo && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setPendingDelete(c);
                      }}
                      className="w-8 h-8 rounded-md flex items-center justify-center text-rose-300 hover:bg-rose-700/30 transition"
                      title="删除"
                      aria-label="删除"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </section>

      {/* 编辑 / 新建表单（inline 展开） */}
      {form && (
        <section
          className="mb-4 rounded-lg p-4"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
            border: '1px solid var(--color-border-subtle)',
          }}
        >
          <h3
            className="text-sm font-medium mb-3"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {form.mode === 'create' ? '新建角色' : `编辑角色 — ${form.name}`}
          </h3>

          <div className="space-y-3">
            <div>
              <label
                className="block text-xs mb-1"
                style={{ color: 'var(--color-text-primary)' }}
              >
                角色名 *
              </label>
              <input
                type="text"
                value={form.name}
                disabled={form.isMomo}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="例：小桃 / Aria / 小助手"
                className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none disabled:opacity-50"
                style={inputStyle}
              />
              {form.isMomo && (
                <p
                  className="text-[10px] mt-1"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  Momo 是默认角色，名称不可修改。
                </p>
              )}
            </div>

            <div>
              <label
                className="block text-xs mb-1"
                style={{ color: 'var(--color-text-primary)' }}
              >
                角色提示词 *
              </label>
              <textarea
                value={form.persona}
                onChange={(e) => setForm({ ...form, persona: e.target.value })}
                placeholder={PERSONA_PLACEHOLDER}
                rows={8}
                className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none resize-y"
                style={inputStyle}
              />
            </div>

            <div>
              <label
                className="block text-xs mb-1"
                style={{ color: 'var(--color-text-primary)' }}
              >
                TTS 声音
              </label>
              <input
                type="text"
                value={form.voice_model}
                onChange={(e) => setForm({ ...form, voice_model: e.target.value })}
                placeholder="例：zh-CN-XiaoxiaoNeural 或 SoVITS模型路径，留空使用全局默认"
                className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
                style={inputStyle}
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label
                  className="block text-xs"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  Live2D 模型
                </label>
                <button
                  type="button"
                  onClick={() => void refreshLive2D()}
                  disabled={live2dLoading}
                  className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
                  style={{ color: 'var(--color-text-secondary)' }}
                  title="重新扫描 frontend/public/live2d/"
                >
                  <RefreshCw
                    size={10}
                    className={live2dLoading ? 'animate-spin' : ''}
                  />
                  刷新
                </button>
              </div>
              <div className="relative">
                <select
                  value={form.live2d_model}
                  onChange={(e) =>
                    setForm({ ...form, live2d_model: e.target.value })
                  }
                  className="w-full appearance-none rounded-md px-2 py-1.5 pr-8 text-sm focus:outline-none"
                  style={inputStyle}
                >
                  <option value="">未绑定（使用静态图片）</option>
                  {/* 当前值不在扫描列表里 → 保留它做"自定义"选项，避免编辑时被改写 */}
                  {form.live2d_model &&
                    !live2dModels.some((m) => m.slug === form.live2d_model) && (
                      <option value={form.live2d_model}>
                        自定义：{form.live2d_model}
                      </option>
                    )}
                  {live2dModels.map((m) => (
                    <option key={m.slug} value={m.slug}>
                      {m.slug} {m.pixi_compatible ? '· 兼容' : '· 不兼容'}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none"
                  style={{ color: 'var(--color-text-secondary)' }}
                />
              </div>
              {/* 选中模型的兼容性 badge + warnings + 自定义 / 加载错误兜底 */}
              {(() => {
                const selected = form.live2d_model
                  ? live2dModels.find((m) => m.slug === form.live2d_model)
                  : null;
                const isCustomOrphan = Boolean(
                  form.live2d_model && !selected,
                );
                return (
                  <>
                    {selected && (
                      <div className="mt-1 flex items-center gap-1 text-[10px]">
                        {selected.pixi_compatible ? (
                          <span
                            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5"
                            style={{
                              background: 'var(--color-accent)',
                              color: 'var(--color-bubble-ai-text)',
                            }}
                          >
                            <CheckCircle2 size={10} />
                            兼容 · {selected.moc3_version_label}
                          </span>
                        ) : (
                          <span
                            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5"
                            style={{
                              background: 'var(--color-bg-elevated)',
                              color: 'var(--color-text-primary)',
                              border: '1px solid var(--color-border)',
                            }}
                          >
                            <AlertTriangle size={10} />
                            不兼容（Cubism 5 / 缺件）
                          </span>
                        )}
                      </div>
                    )}
                    {selected && selected.warnings.length > 0 && (
                      <div
                        className="mt-1 flex items-start gap-1 text-[10px]"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        <AlertTriangle
                          size={10}
                          className="flex-shrink-0 mt-[1px]"
                        />
                        <span>{selected.warnings.join('；')}</span>
                      </div>
                    )}
                    {isCustomOrphan && (
                      <div
                        className="mt-1 flex items-start gap-1 text-[10px]"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        <AlertTriangle
                          size={10}
                          className="flex-shrink-0 mt-[1px]"
                        />
                        <span>
                          目录里没扫到 “{form.live2d_model}”。检查
                          frontend/public/live2d/ 下是否有该 slug，或点刷新。
                        </span>
                      </div>
                    )}
                  </>
                );
              })()}
              {live2dError && (
                <p
                  className="text-[10px] mt-1"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  列表加载失败：{live2dError}
                </p>
              )}
              <p
                className="text-[10px] mt-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                选项来自 frontend/public/live2d/。新角色资产请先放进对应 slug
                目录，详见 frontend/public/live2d/README.md。
              </p>
            </div>

            <div>
              <label
                className="block text-xs mb-1"
                style={{ color: 'var(--color-text-primary)' }}
              >
                头像路径
              </label>
              <input
                type="text"
                value={form.avatar_path}
                onChange={(e) => setForm({ ...form, avatar_path: e.target.value })}
                placeholder="图片绝对路径，留空使用默认立绘"
                className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
                style={inputStyle}
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={cancelForm}
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
                onClick={submitForm}
                disabled={submitting || !formValid}
                className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background: 'var(--color-accent)',
                  color: 'var(--color-bubble-user-text)',
                }}
              >
                {submitting ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        </section>
      )}

      {pendingDelete && (
        <ConfirmModal
          text={`确认删除角色「${pendingDelete.name}」？\n该角色名下的对话与记忆不会自动迁移。`}
          onConfirm={confirmDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      {/* Toasts */}
      <div className="fixed bottom-4 right-4 z-40 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="text-sm px-3 py-2 rounded shadow-lg"
            style={{
              background: 'color-mix(in srgb, var(--color-bg-surface) 90%, transparent)',
              border: '1px solid rgba(244, 63, 94, 0.6)',
              color: 'var(--color-text-primary)',
            }}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

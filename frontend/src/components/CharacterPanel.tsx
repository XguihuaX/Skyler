import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
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
import {
  fetchLive2DModels,
  type Live2DUploadResult,
} from '../lib/live2d';
import Live2DDropzone from './live2d/Live2DDropzone';
import MotionMapConfirmDialog from './live2d/MotionMapConfirmDialog';
import SplashArtDropzone from './character/SplashArtDropzone';
import VoiceLinesSection from './character/VoiceLinesSection';
import VoicePicker from './character/VoicePicker';
import { deleteSplashArt } from '../lib/characters';
import {
  fetchBackgrounds,
  type BackgroundItem,
} from '../lib/backgrounds';
// v4 segment 2:Persona variant 编辑入口取代老 persona textarea
import PersonaEditorModal from './PersonaEditorModal';
import {
  type CharacterPersonaRow,
  activatePersona,
  deletePersona,
  listPersonas,
  restorePersonaToBuiltin,
} from '../lib/personas';

const DEFAULT_CHARACTER_NAME = 'Momo';

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
  voice_model: string;
  live2d_model: string;
  avatar_path: string;
  // v3.5 chunk 5a：每角色背景层。空串 = "(无)"，保存时落库 NULL。
  background_path: string;
}

const EMPTY_FORM: FormState = {
  mode: 'create',
  id: null,
  isMomo: false,
  name: '',
  voice_model: '',
  live2d_model: '',
  avatar_path: '',
  background_path: '',
};

// v4 segment 2:删旧 PERSONA_PLACEHOLDER + 角色提示词 textarea。persona 编辑
// 入口改为 "Personas" 区域 + PersonaEditorModal (Tier-1 7 字段 + 滑块)。

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
// v4 segment 2 — PersonasSection
// Inline 嵌入编辑表单内,列 character_personas + 编辑 / 激活 / 删除 / 还原。
// 单独组件让 CharacterPanel 主流不复杂化;PersonaEditorModal 由本组件管开关。
// ---------------------------------------------------------------------------

interface PersonasSectionProps {
  characterId: number;
  showToast: (text: string) => void;
}

function PersonasSection({ characterId, showToast }: PersonasSectionProps) {
  const [personas, setPersonas] = useState<CharacterPersonaRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<CharacterPersonaRow | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listPersonas(characterId);
      setPersonas(rows);
    } catch (e) {
      showToast(`加载 persona 失败:${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [characterId, showToast]);

  useEffect(() => { void refresh(); }, [refresh]);

  const onActivate = async (p: CharacterPersonaRow) => {
    try {
      const r = await activatePersona(p.id);
      showToast(
        r.just_switched
          ? `已激活 「${p.variant_name}」 — 下条对话会用新风格`
          : `「${p.variant_name}」 已是激活状态`,
      );
      await refresh();
    } catch (e) {
      showToast(`激活失败:${(e as Error).message}`);
    }
  };

  const onDelete = async (p: CharacterPersonaRow) => {
    if (p.is_active) {
      showToast('激活中的 variant 不能删除,先激活其他');
      return;
    }
    if (!window.confirm(`确认删除 persona variant 「${p.variant_name}」?`)) return;
    try {
      await deletePersona(p.id);
      showToast(`已删除 「${p.variant_name}」`);
      await refresh();
    } catch (e) {
      showToast(`删除失败:${(e as Error).message}`);
    }
  };

  const onRestore = async (p: CharacterPersonaRow) => {
    if (!p.is_builtin) return;
    if (!window.confirm(`恢复 「${p.variant_name}」 到出厂默认?会覆盖你的编辑内容`)) return;
    try {
      await restorePersonaToBuiltin(p.id);
      showToast(`「${p.variant_name}」 已恢复出厂`);
      await refresh();
    } catch (e) {
      showToast(`恢复失败:${(e as Error).message}`);
    }
  };

  const cardStyle: React.CSSProperties = {
    background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
    border: '1px solid var(--color-border-subtle)',
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <label
          className="text-xs font-medium"
          style={{ color: 'var(--color-text-primary)' }}
        >
          Personas (人设 variant)
        </label>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-bubble-user-text)',
          }}
        >
          <Plus size={12} /> 新建 variant
        </button>
      </div>

      {loading && personas.length === 0 ? (
        <p
          className="text-[11px] py-2"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          加载中...
        </p>
      ) : personas.length === 0 ? (
        <p
          className="text-[11px] py-2"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          (无 persona variant — 新建一个开始编辑)
        </p>
      ) : (
        <div className="space-y-2">
          {personas.map((p) => {
            const subtitle = (p.identity?.name || '').trim() || '(未填 identity.name)';
            return (
              <div key={p.id} className="rounded-md p-2.5" style={cardStyle}>
                <div className="flex items-center gap-2">
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{
                      background: p.is_active
                        ? 'var(--color-accent)'
                        : 'var(--color-text-secondary)',
                    }}
                    title={p.is_active ? '当前激活' : '未激活'}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className="text-sm font-medium truncate"
                        style={{ color: 'var(--color-text-primary)' }}
                      >
                        {p.variant_name}
                      </span>
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                        style={{
                          background: p.is_builtin
                            ? 'color-mix(in srgb, var(--color-accent) 50%, transparent)'
                            : 'var(--color-bg-elevated)',
                          color: 'var(--color-text-primary)',
                        }}
                      >
                        {p.is_builtin ? '系统预设' : '自定义'}
                      </span>
                      {p.is_active && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                          style={{
                            background: 'var(--color-accent)',
                            color: 'var(--color-bubble-user-text)',
                          }}
                        >
                          ★ 当前激活
                        </span>
                      )}
                    </div>
                    <p
                      className="text-[11px] mt-0.5 truncate"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      {subtitle}{p.description ? ` — ${p.description}` : ''}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1 mt-2 flex-wrap">
                  <button
                    type="button"
                    onClick={() => setEditing(p)}
                    className="text-[11px] px-2 py-1 rounded hover:opacity-80"
                    style={{
                      background: 'var(--color-bg-input)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text-primary)',
                    }}
                  >
                    编辑
                  </button>
                  {!p.is_active && (
                    <button
                      type="button"
                      onClick={() => void onActivate(p)}
                      className="text-[11px] px-2 py-1 rounded hover:opacity-80"
                      style={{
                        background: 'var(--color-accent)',
                        color: 'var(--color-bubble-user-text)',
                      }}
                    >
                      激活
                    </button>
                  )}
                  {p.is_builtin && (
                    <button
                      type="button"
                      onClick={() => void onRestore(p)}
                      className="text-[11px] px-2 py-1 rounded hover:opacity-80"
                      style={{
                        background: 'var(--color-bg-input)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-secondary)',
                      }}
                      title="恢复出厂默认 (从 builtin_seed 备份)"
                    >
                      恢复默认
                    </button>
                  )}
                  {!p.is_active && (
                    <button
                      type="button"
                      onClick={() => void onDelete(p)}
                      className="text-[11px] px-2 py-1 rounded text-rose-300 hover:bg-rose-700/30"
                    >
                      删除
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {(editing || showCreate) && (
        <PersonaEditorModal
          characterId={characterId}
          existing={editing}
          onClose={() => { setEditing(null); setShowCreate(false); }}
          onSaved={async () => {
            setEditing(null);
            setShowCreate(false);
            await refresh();
          }}
        />
      )}
    </div>
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

  // INV-11 Stage 1.5 paradigm B (2026-05-26): TTS provider/model/voice 内化
  // 进 character/VoicePicker · CharacterPanel 不再持有 ttsProviders /
  // clonedVoices / voiceAliases / ttsLoading state(VoicePicker 自己 fetch
  // /api/tts/providers nested tree + aliases · 一屏 inline 显示)。

  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [loading, setLoading]       = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm]             = useState<FormState | null>(null); // null = 不显示表单
  const [pendingDelete, setPendingDelete] = useState<CharacterRow | null>(null);
  const [toasts, setToasts]         = useState<ToastInfo[]>([]);
  const [live2dLoading, setLive2dLoading] = useState(false);
  const [live2dError,   setLive2dError]   = useState<string | null>(null);
  // v3.5 chunk 5a：背景资产清单（GET /api/backgrounds）。空数组 = 未扫
  // 到，下拉退化为只有 "(无)"。
  const [backgrounds, setBackgrounds]     = useState<BackgroundItem[]>([]);
  const [bgLoading, setBgLoading]         = useState(false);
  const [bgError,   setBgError]           = useState<string | null>(null);
  // v4-fan chunk 5: splash art 删除确认对话框 target(point to character row,
  // 拿名字 + id 给确认文案;upload 不需要 confirm,直接走 SplashArtDropzone)
  const [pendingSplashDelete, setPendingSplashDelete] =
    useState<CharacterRow | null>(null);
  const [splashDeleting, setSplashDeleting] = useState(false);

  // Stage 2.2.1: Live2D dropzone modal + 上传成功后的 motion_map 确认弹窗
  const [showLive2DUpload, setShowLive2DUpload] = useState(false);
  const [pendingMotionMap, setPendingMotionMap] = useState<{
    targetCharacterId: number;
    targetCharacterName: string;
    result: Live2DUploadResult;
  } | null>(null);
  const [applyingMotionMap, setApplyingMotionMap] = useState(false);

  // v4 segment 2:列表预览改成 active variant 名;loads after characters fetch
  const [activeVariantNames, setActiveVariantNames] =
    useState<Map<number, string>>(new Map());

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

      // v4 segment 2:并行拿每个 character 的 active variant 名,失败 silent
      // (load_active_persona 没有对应行时 server 返 404,前端 fallthrough)
      const entries = await Promise.all(
        rows.map(async (c) => {
          try {
            const list = await listPersonas(c.id);
            const active = list.find((p) => p.is_active);
            const display = active?.identity?.name?.trim()
              ? active.identity.name.trim()
              : active?.variant_name ?? '';
            return [c.id, display] as const;
          } catch {
            return [c.id, ''] as const;
          }
        }),
      );
      const map = new Map<number, string>();
      for (const [cid, name] of entries) {
        if (name) map.set(cid, name);
      }
      setActiveVariantNames(map);
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

  // Stage 2.2.1: Live2D dropzone 上传成功回调
  //
  // 流程:
  //   1. toast 带 textures / motions 计数
  //   2. 自动设置 form.live2d_model = result.slug(让 dropdown 选中新模型)
  //   3. await refreshLive2D() 让 dropdown 列表立即出现新 slug
  //   4. 仅 edit 模式 + 有 motion entries 时弹 motion_map 确认对话框;
  //      create 模式提示用户保存角色后再配,本组件无 character.id 不能 PATCH
  const onLive2DUploadSuccess = useCallback(
    async (result: Live2DUploadResult) => {
      setShowLive2DUpload(false);
      const motionCount = result.motions_count;
      const textureCount = result.textures_count;
      showToast(
        `已上传 ${result.slug}(${textureCount} 个 texture / ${motionCount} 个 motion)`,
      );
      // 自动选中新 slug + 刷新 dropdown
      setForm((prev) => (prev ? { ...prev, live2d_model: result.slug } : prev));
      await refreshLive2D();

      // 决定是否弹 motion_map 确认对话框
      setForm((curr) => {
        if (!curr) return curr;
        if (
          curr.mode === 'edit'
          && curr.id !== null
          && Object.keys(result.motion_map).length > 0
        ) {
          setPendingMotionMap({
            targetCharacterId: curr.id,
            targetCharacterName: curr.name || `character ${curr.id}`,
            result,
          });
        } else if (
          curr.mode === 'create'
          && Object.keys(result.motion_map).length > 0
        ) {
          showToast(
            'motion_map 默认值已就绪;保存角色后可在 motion_map_json 编辑',
          );
        }
        return curr;
      });
    },
    [refreshLive2D, showToast],
  );

  const onApplyMotionMap = useCallback(async () => {
    if (!pendingMotionMap) return;
    setApplyingMotionMap(true);
    try {
      await patchCharacter(pendingMotionMap.targetCharacterId, {
        motion_map_json: JSON.stringify(pendingMotionMap.result.motion_map),
      });
      showToast(`已应用 motion_map 到 ${pendingMotionMap.targetCharacterName}`);
      setPendingMotionMap(null);
      await refresh();
    } catch (e) {
      console.error('[CharacterPanel] apply motion_map failed:', e);
      showToast(`应用 motion_map 失败:${(e as Error).message}`);
    } finally {
      setApplyingMotionMap(false);
    }
  }, [pendingMotionMap, refresh, showToast]);

  const onSkipMotionMap = useCallback(() => {
    setPendingMotionMap(null);
    showToast(
      '已跳过 motion_map;可在 character.motion_map_json 字段手动配置',
    );
  }, [showToast]);

  // v4-fan chunk 5: splash art 上传成功 → toast + refresh characters
  // (拉新 splash_art_url 同步进 store / 本地 state, Gallery 切回时
  // 背景自动跟着变,因为读 store reactive)
  const onSplashUploadSuccess = useCallback(
    async (newUrl: string) => {
      showToast(`立绘已更新 (${newUrl})`);
      await refresh();
    },
    [refresh, showToast],
  );

  // v4-fan chunk 5: splash art 删除确认 → 调 backend DELETE → refresh
  const confirmSplashDelete = useCallback(async () => {
    const target = pendingSplashDelete;
    if (!target) return;
    setSplashDeleting(true);
    try {
      await deleteSplashArt(target.id);
      showToast(`已删除 ${target.name} 的立绘`);
      setPendingSplashDelete(null);
      await refresh();
    } catch (e) {
      console.error('[CharacterPanel] delete splash art failed:', e);
      const err = e as Error & { status?: number };
      showToast(
        `删除失败:${err.status ? err.status + ' · ' : ''}${err.message}`,
      );
    } finally {
      setSplashDeleting(false);
    }
  }, [pendingSplashDelete, refresh, showToast]);

  // v3.5 chunk 5a：背景资产 mount 时拉一次，[刷新] 按钮 + 新增 / 编辑表单
  // 打开时复用 callback。失败不阻塞主路径——下拉只剩 "(无)"，用户能继续
  // 编辑其他字段。
  const refreshBackgrounds = useCallback(async () => {
    setBgLoading(true);
    setBgError(null);
    try {
      const data = await fetchBackgrounds();
      setBackgrounds(data.items);
    } catch (e) {
      const msg = (e as Error).message;
      console.error('[CharacterPanel] backgrounds fetch failed:', e);
      setBgError(msg);
    } finally {
      setBgLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshBackgrounds();
  }, [refreshBackgrounds]);

  // INV-11 Stage 1.5 paradigm B: TTS provider/voice fetch 内化进 VoicePicker
  // (自己 fetch /api/tts/providers nested tree + voice aliases)· CharacterPanel
  // 不再持有这些 state。

  const startCreate = () => {
    setForm({ ...EMPTY_FORM, mode: 'create' });
  };

  const startEdit = (c: CharacterRow) => {
    setForm({
      mode: 'edit',
      id: c.id,
      isMomo: c.name === DEFAULT_CHARACTER_NAME,
      name: c.name,
      voice_model: c.voice_model ?? '',
      live2d_model: c.live2d_model ?? '',
      avatar_path: c.avatar_path ?? '',
      background_path: c.background_path ?? '',
    });
  };

  const cancelForm = () => setForm(null);

  const submitForm = async () => {
    if (!form) return;
    const name           = form.name.trim();
    const voiceModel     = form.voice_model.trim();
    const live2dModel    = form.live2d_model.trim();
    const avatarPath     = form.avatar_path.trim();
    const backgroundPath = form.background_path.trim();
    if (!name) {
      showToast('角色名是必填项');
      return;
    }
    setSubmitting(true);
    try {
      if (form.mode === 'create') {
        // v4 segment 2:create 不再要求 persona text。后端 characters.persona
        // 仍是 NOT NULL,临时占位字符串;真人设存 character_personas。
        // 创建后用户应去 "Personas" 区域编辑 default variant 字段。
        await createCharacter({
          name,
          persona: `(v4 placeholder for ${name}; edit Personas panel instead)`,
          avatar_path: avatarPath || null,
          voice_model: voiceModel || null,
          live2d_model: live2dModel || null,
          background_path: backgroundPath || null,
        });
      } else if (form.id !== null) {
        // Momo(id=1) 名字不可改 — 即使前端表单 disabled，这里也排除掉。
        // v4 segment 2:patch 不再覆写 persona 字段(后端字段还在,只是 renderer
        // 不读它了)。
        await patchCharacter(form.id, {
          ...(form.isMomo ? {} : { name }),
          avatar_path: avatarPath || null,
          voice_model: voiceModel || null,
          live2d_model: live2dModel || null,
          background_path: backgroundPath || null,
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

  const formValid = !!form && !!form.name.trim();

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
            // v4 segment 2:列表 preview 改成显示 active variant 名(从父级
            // activeVariantNames Map 取),拿不到时 fall back 到 "(未设置 persona)"。
            const activeVariantName = activeVariantNames.get(c.id);
            const preview = activeVariantName
              ? `${c.name} / ${activeVariantName}`
              : '(未设置 persona)';
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

            {/* v4 segment 2:旧 "角色提示词" textarea 已删除。
                Persona 内核(7 字段 Tier-1)在下方 "Personas" 区域编辑(PersonaEditorModal)。 */}
            {form.mode === 'edit' && form.id !== null && (
              <PersonasSection
                characterId={form.id}
                showToast={showToast}
              />
            )}

            {/* v4.0 voice greeting (2026-05-22) · 立绘馆放大 onEnter 随机播 */}
            {form.mode === 'edit' && form.id !== null && (
              <VoiceLinesSection
                characterId={form.id}
                showToast={showToast}
              />
            )}
            {form.mode === 'create' && (
              <p
                className="text-[11px] rounded-md p-2"
                style={{
                  background: 'color-mix(in srgb, var(--color-accent) 12%, transparent)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                ⓘ 创建后,在编辑此角色时会出现 <b>Personas</b> 区域,可编辑
                身份卡 / 性格 / 说话风格 / voice_samples 等 7 字段。
              </p>
            )}

            {/* INV-11 Stage 1.5 paradigm B (2026-05-26): inline VoicePicker —
                provider × model × voice 3 级 dropdown 一屏可见 · dropdown
                change → 自动 PATCH(debounce 300ms · edit 模式)。取代旧
                ttsProviders 简化下拉 + VoicePickerModal 入口 button。 */}
            <VoicePicker
              voiceModel={form.voice_model}
              characterId={form.mode === 'edit' ? form.id : null}
              characterName={form.name || undefined}
              onVoiceModelChange={(json) =>
                setForm((f) => (f ? { ...f, voice_model: json } : f))
              }
              showToast={showToast}
              inputStyle={inputStyle}
            />

            <div>
              <div className="flex items-center justify-between mb-1">
                <label
                  className="block text-xs"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  Live2D 模型
                </label>
                <div className="flex items-center gap-1">
                  {/* Stage 2.2.1: 上传新模型按钮 */}
                  <button
                    type="button"
                    onClick={() => setShowLive2DUpload(true)}
                    className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80"
                    style={{
                      background: 'var(--color-accent)',
                      color: 'var(--color-bubble-user-text)',
                    }}
                    title="拖入 .zip 上传新 Live2D 模型"
                  >
                    <Upload size={10} />
                    上传模型
                  </button>
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

            {/* v4-fan chunk 5 — Splash art 上传 / 删除。仅 edit 模式渲染:
                upload endpoint 需要 character.id, create 模式还没保存就没
                id 可挂。create 时给一句"先保存再上传"提示。 */}
            <div>
              <label
                className="block text-xs mb-1"
                style={{ color: 'var(--color-text-primary)' }}
              >
                角色立绘
              </label>
              {form.mode === 'edit' && form.id !== null ? (
                <SplashArtDropzone
                  characterId={form.id}
                  currentUrl={
                    characters.find((c) => c.id === form.id)?.splash_art_url ?? null
                  }
                  onUploadSuccess={onSplashUploadSuccess}
                  onDeleteRequest={() => {
                    const target = characters.find((c) => c.id === form.id);
                    if (target) setPendingSplashDelete(target);
                  }}
                />
              ) : (
                <p
                  className="text-[11px] py-2"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  保存角色后即可上传立绘。
                </p>
              )}
              <p
                className="text-[10px] mt-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                用于 Character Gallery 卡片视觉。推荐 1024×1536 / 2:3,&lt; 5 MB。
              </p>
            </div>

            {/* v3.5 chunk 5a — 每角色背景层（image / video）。Live2D 在
                背景层之上，仍正常显示。第一项 "(无)" → 保存 null，回退到
                原 fallback 链。 */}
            <div>
              <div className="flex items-baseline justify-between mb-1">
                <label
                  className="block text-xs"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  背景层
                </label>
                <button
                  type="button"
                  onClick={() => void refreshBackgrounds()}
                  disabled={bgLoading}
                  className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
                  style={{ color: 'var(--color-text-secondary)' }}
                  title="重新扫描 frontend/public/backgrounds/"
                >
                  <RefreshCw
                    size={10}
                    className={bgLoading ? 'animate-spin' : ''}
                  />
                  刷新
                </button>
              </div>
              <div className="relative">
                <select
                  value={form.background_path}
                  onChange={(e) =>
                    setForm({ ...form, background_path: e.target.value })
                  }
                  className="w-full appearance-none rounded-md px-2 py-1.5 pr-8 text-sm focus:outline-none"
                  style={inputStyle}
                >
                  <option value="">(无 —— 使用默认 fallback)</option>
                  {/* 当前 background_path 不在扫描列表里 → 保留它做"自定义"
                      避免编辑时被改写（与 live2d 同 pattern）。 */}
                  {form.background_path &&
                    !backgrounds.some((b) => b.path === form.background_path) && (
                      <option value={form.background_path}>
                        自定义：{form.background_path}
                      </option>
                    )}
                  {backgrounds.map((b) => (
                    <option key={b.path} value={b.path}>
                      [{b.type === 'image' ? '图' : '视频'}] {b.name}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none"
                  style={{ color: 'var(--color-text-secondary)' }}
                />
              </div>
              {/* 预览框 120×80 */}
              {form.background_path && (() => {
                const selected = backgrounds.find(
                  (b) => b.path === form.background_path,
                );
                const inferredType = selected?.type
                  ?? (/\.(mp4|webm)$/i.test(form.background_path) ? 'video' : 'image');
                return (
                  <div
                    className="mt-2 rounded overflow-hidden"
                    style={{
                      width: 120, height: 80,
                      border: '1px solid var(--color-border)',
                      background: 'var(--color-bg-elevated)',
                    }}
                  >
                    {inferredType === 'image' ? (
                      <img
                        src={form.background_path}
                        alt=""
                        className="w-full h-full"
                        style={{ objectFit: 'cover' }}
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.opacity = '0.2';
                        }}
                      />
                    ) : (
                      <video
                        key={form.background_path}
                        src={form.background_path}
                        autoPlay
                        loop
                        muted
                        playsInline
                        className="w-full h-full"
                        style={{ objectFit: 'cover' }}
                      />
                    )}
                  </div>
                );
              })()}
              {bgError && (
                <p
                  className="text-[10px] mt-1"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  列表加载失败：{bgError}
                </p>
              )}
              <p
                className="text-[10px] mt-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                选项来自 frontend/public/backgrounds/（含一层子目录）。
                后缀白名单：jpg / png / webp / mp4 / webm。详见目录下 README.md。
              </p>
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

      {/* v4-fan chunk 5: splash art 删除确认 */}
      {pendingSplashDelete && (
        <ConfirmModal
          text={
            `删除「${pendingSplashDelete.name}」的立绘？\n`
            + '删除后该角色将回退到默认占位图(???)。后续可随时重新上传。'
            + (splashDeleting ? '\n\n（删除中…）' : '')
          }
          onConfirm={() => void confirmSplashDelete()}
          onCancel={() => {
            if (!splashDeleting) setPendingSplashDelete(null);
          }}
        />
      )}

      {/* Stage 2.2.1: Live2D 上传 + motion_map 确认 */}
      {showLive2DUpload && (
        <Live2DDropzone
          onClose={() => setShowLive2DUpload(false)}
          onSuccess={(result) => void onLive2DUploadSuccess(result)}
        />
      )}
      {pendingMotionMap && (
        <MotionMapConfirmDialog
          characterName={pendingMotionMap.targetCharacterName}
          slug={pendingMotionMap.result.slug}
          motionMap={pendingMotionMap.result.motion_map}
          applying={applyingMotionMap}
          onApply={() => void onApplyMotionMap()}
          onSkip={onSkipMotionMap}
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

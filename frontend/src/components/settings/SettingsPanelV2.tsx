import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Bell,
  Brain,
  Clipboard,
  Database,
  Eye,
  Info,
  Palette,
  Rocket,
  UserCog,
  Users,
} from 'lucide-react';
import { useAppStore } from '../../store';
// bugfix-3.3: lib/models.ts 下线 (旧 /api/settings/model 路径)。AboutSection 改走
// /api/ai-providers?type=llm 找 is_active=true 的 provider 显示。
import { listProvidersByType } from '../../lib/ai_providers';
import ActivityAwarenessSection from '../ActivityAwarenessSection';
import ActivityTimelineDrawer from '../ActivityTimelineDrawer';
import CharacterPanel from '../CharacterPanel';
import MemoryManagerDrawer from '../MemoryManagerDrawer';
import {
  ActivityTimelineSection,
  CharacterStateSection,
  ClipboardSection,
  MemorySection,
  MemoryTogglesSection,
  ProactiveSection,
  ProfileSection,
  SplashSection,
  ThemeSection,
} from '../SettingsPanelLegacy';
import UserProfileSection from '../UserProfileSection';
import GlassAppearanceSection from './GlassAppearanceSection';
import TwoPaneShell, { type PaneSection } from '../TwoPaneShell';
import {
  deleteBackground,
  fetchBackgrounds,
  resolveBackgroundUrl,
  uploadBackground,
  userFilenameFromItem,
  type BackgroundItem,
} from '../../lib/backgrounds';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';

/**
 * bugfix-2.2: ⚙ 设置 V2 (Settings V2) — "Skyler 自身行为偏好"
 *
 * 10 个 section(对照 bugfix-2.2 spec 顺序):
 *   1. 👥 角色管理     —— CharacterPanel
 *   2. ✨ 主动陪伴     —— ProactiveSection
 *   3. 👁 活动感知     —— ActivityAwarenessSection + ActivityTimelineSection
 *   4. 📋 剪贴板       —— ClipboardSection
 *   5. 🎭 角色状态     —— CharacterStateSection
 *   6. 🧠 记忆         —— MemorySection + MemoryTogglesSection(长期/画像/搜索)
 *   7. 👤 用户档案     —— ProfileSection(称呼/语言) + UserProfileSection(profile_data)
 *   8. 🚀 启动         —— SplashSection
 *   9. 🎨 外观         —— ThemeSection
 *  10. ℹ 关于         —— app + LLM model + GitHub
 *
 * 老 SettingsPanel 完全废弃,sidebar 没有入口。本面板共享 toast(Panel.tsx
 * 顶层提供)、内含 MemoryManagerDrawer / ActivityTimelineDrawer mount。
 */

interface SettingsPanelV2Props {
  showToast: (text: string) => void;
}

export default function SettingsPanelV2({ showToast }: SettingsPanelV2Props) {
  const [activeId, setActiveId] = useState<string>('characters');

  const defaultUserId      = useAppStore((s) => s.defaultUserId);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);

  // bugfix-2.2: 把 Memory drawer 与 Activity timeline drawer mount 提到面板
  // 顶层(原 SettingsPanel 也是这样做的),让任一子 section 都能打开。
  const [memoryManagerOpen, setMemoryManagerOpen] = useState(false);
  const [timelineDrawerOpen, setTimelineDrawerOpen] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);

  const sections: PaneSection[] = [
    {
      id: 'characters',
      label: '角色管理',
      Icon: Users,
      render: () => (
        <div className="flex-1 flex flex-col overflow-hidden">
          <CharacterPanel />
        </div>
      ),
    },
    {
      id: 'proactive',
      label: '主动陪伴',
      Icon: Bell,
      render: () => (
        <div className="p-6">
          <ProactiveSection showToast={showToast} />
        </div>
      ),
    },
    {
      id: 'activity',
      label: '活动感知',
      Icon: Eye,
      render: () => (
        <div className="p-6">
          <ActivityAwarenessSection showToast={showToast} />
          <ActivityTimelineSection
            onOpenTimeline={() => setTimelineDrawerOpen(true)}
          />
        </div>
      ),
    },
    {
      id: 'clipboard',
      label: '剪贴板',
      Icon: Clipboard,
      render: () => (
        <div className="p-6">
          <ClipboardSection showToast={showToast} />
        </div>
      ),
    },
    {
      id: 'character_state',
      label: '角色状态',
      Icon: Brain,
      render: () => (
        <div className="p-6">
          <CharacterStateSection showToast={showToast} />
        </div>
      ),
    },
    {
      id: 'memory',
      label: '记忆',
      Icon: Database,
      render: () => (
        <div className="p-6">
          <MemorySection
            userId={defaultUserId}
            characterId={currentCharacterId}
            showToast={showToast}
            managerOpen={memoryManagerOpen}
            onOpenManager={() => setMemoryManagerOpen(true)}
            onCountChange={setMemoryCount}
            count={memoryCount}
          />
          <MemoryTogglesSection showToast={showToast} />
        </div>
      ),
    },
    {
      id: 'profile',
      label: '用户档案',
      Icon: UserCog,
      render: () => (
        <div className="p-6">
          <ProfileSection userId={defaultUserId} showToast={showToast} />
          <UserProfileSection userId={defaultUserId} showToast={showToast} />
        </div>
      ),
    },
    {
      id: 'startup',
      label: '启动',
      Icon: Rocket,
      render: () => (
        <div className="p-6">
          <SplashSection />
        </div>
      ),
    },
    {
      id: 'appearance',
      label: '外观',
      Icon: Palette,
      render: () => (
        <div className="p-6 space-y-8">
          <ThemeSection />
          {/* 2026-06-02 · UI redesign step 1 · 全局场景背景层(壁纸)选择 ·
              主题(8 套色)只换 --color-* token,场景独立于色之上。 */}
          <SceneSection />
          {/* 2026-06-20 · 玻璃外观自定义(色环 + 不透明度 + 文字对比)·
              全局覆盖叠在主题之上 · 切主题保留 · 可恢复默认。 */}
          <GlassAppearanceSection />
        </div>
      ),
    },
    {
      id: 'about',
      label: '关于',
      Icon: Info,
      render: () => <AboutSection />,
    },
  ];

  return (
    <>
      <TwoPaneShell
        title="设置"
        sections={sections}
        activeId={activeId}
        onActiveChange={setActiveId}
      />

      {/* Drawers mounted at panel root —— 任一 section 都能触发打开 */}
      <MemoryManagerDrawer
        open={memoryManagerOpen}
        userId={defaultUserId}
        characterId={currentCharacterId}
        onClose={() => setMemoryManagerOpen(false)}
        onCountChange={setMemoryCount}
      />
      <ActivityTimelineDrawer
        open={timelineDrawerOpen}
        onClose={() => setTimelineDrawerOpen(false)}
        showToast={showToast}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// 2026-06-02 · UI redesign step 1 · 场景背景层(壁纸)section
// 主题(8 套色)只换 --color-* token,场景独立于色之上 · 全局共享、跨角色。
// 2026-06-04 · Round 5 step1:解耦 per-character bg(SceneBackground 不再读
// character.background_path)· UI 改成 fetchBackgrounds() 缩略图网格 · 点选即时
// 生效(无需"应用"按钮)· 手填路径降级成折叠 <details> advanced 高级入口。
// ---------------------------------------------------------------------------

function SceneSection() {
  const globalScene    = useAppStore((s) => s.globalScene);
  const setGlobalScene = useAppStore((s) => s.setGlobalScene);

  const [items, setItems]     = useState<BackgroundItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBackgrounds();
      setItems(data.items);
    } catch (e) {
      const msg = (e as Error).message;
      console.error('[SceneSection] fetchBackgrounds failed:', e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // currentSig:globalScene.path 是 resolved 浏览器 URL(bundled 相对、user 含
  // BACKEND_BASE)。tile selected 判定要跟同款 resolved URL 比,所以这里直接拿
  // globalScene.path 即可,不需 source 字段。
  const currentSig = globalScene?.path ?? null;

  // Round 5 step2 上传 · 文件 + 名字 form state
  // 跟 backend _MAX_UPLOAD_BYTES 同款 · 改阈值要两处一起改(或后端 ENV 给 frontend 拉)。
  const MAX_UPLOAD_MB = 200;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [uploadName, setUploadName]   = useState<string>('');
  const [uploading, setUploading]     = useState(false);
  const [uploadErr, setUploadErr]     = useState<string | null>(null);

  const onPickFile = () => fileInputRef.current?.click();
  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    // 清掉 input value 让用户能重选同一文件
    e.target.value = '';
    if (!f) { setPendingFile(null); return; }
    // 预检:超大直接 inline 报错,不进命名表单也不发请求。
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setPendingFile(null);
      setUploadName('');
      setUploadErr(
        `文件 ${(f.size / (1024 * 1024)).toFixed(1)} MB 超过 ${MAX_UPLOAD_MB} MB 上限`,
      );
      return;
    }
    setUploadErr(null);
    setPendingFile(f);
    if (uploadName.trim() === '') {
      // 默认名字 = 原文件名 stem(用户可改)
      const stem = f.name.replace(/\.[^.]+$/, '');
      setUploadName(stem);
    }
  };

  const submitUpload = async () => {
    if (!pendingFile) return;
    setUploading(true);
    setUploadErr(null);
    try {
      await uploadBackground(pendingFile, uploadName.trim());
      setPendingFile(null);
      setUploadName('');
      await refresh();
    } catch (e) {
      setUploadErr((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const cancelUpload = () => {
    setPendingFile(null);
    setUploadName('');
    setUploadErr(null);
  };

  // Round 5 step2 删除 · 改成 inline 确认条(不依赖 window.confirm —— Tauri 2
  // macOS WKWebView 下 native confirm 经常静默返 false,造成"点了删除没反应"的
  // 假象,根本没发 fetch)。流程:点 Trash → confirmDelete 记录目标 item →
  // 网格下方出现一条"确认要删除「xx」吗" + [取消/确认] 双按钮 → 确认才发请求。
  const [confirmDelete, setConfirmDelete] = useState<BackgroundItem | null>(null);
  const [deleting, setDeleting]           = useState(false);
  const [deleteErr, setDeleteErr]         = useState<string | null>(null);

  const askDelete = (item: BackgroundItem) => {
    setConfirmDelete(item);
    setDeleteErr(null);
  };
  const cancelDelete = () => {
    setConfirmDelete(null);
    setDeleteErr(null);
  };
  const doDelete = async () => {
    if (!confirmDelete) return;
    const filename = userFilenameFromItem(confirmDelete);
    if (!filename) { setConfirmDelete(null); return; }
    setDeleting(true);
    setDeleteErr(null);
    try {
      await deleteBackground(filename);
      // 删后若 globalScene 指向它,顺手清掉防止死链。
      if (currentSig && currentSig.endsWith(confirmDelete.path)) {
        setGlobalScene(null);
      }
      setConfirmDelete(null);
      await refresh();
    } catch (e) {
      setDeleteErr((e as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  // 高级:手填路径(默认折叠)。draft 仅在打开 advanced 后初始化。
  const [draftType, setDraftType] = useState<'image' | 'video'>(globalScene?.type ?? 'image');
  const [draftPath, setDraftPath] = useState<string>(globalScene?.path ?? '');

  const applyDraft = () => {
    const trimmed = draftPath.trim();
    if (trimmed === '') {
      setGlobalScene(null);
      return;
    }
    setGlobalScene({ type: draftType, path: trimmed });
  };

  return (
    <section>
      <div className="flex items-baseline justify-between mb-1">
        <h3
          className="text-base font-medium"
          style={{ color: 'var(--color-text-primary)' }}
        >
          🖼 场景背景
        </h3>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="text-[11px] inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
          style={{ color: 'var(--color-text-secondary)' }}
          aria-label="重新扫描 backgrounds 目录"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>
      <p
        className="text-xs mb-3"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        全局壁纸 · 跨角色共享 · 独立于配色主题 · 切角色不会换。
        默认样例随 app 内置(只读),自传的图存到 OS appData,可加可删。
        后缀白名单 jpg / png / webp / mp4 / webm · 点缩略图即应用。
      </p>

      {/* 缩略图网格 · "无壁纸"+ "添加" + 已扫描资产 */}
      <div
        className="rounded-lg p-3"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
          border: '1px solid var(--color-border-subtle)',
        }}
      >
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))' }}
        >
          {/* "无壁纸" 单元(清除 globalScene)*/}
          <BackgroundTile
            label="无壁纸"
            kind="none"
            selected={currentSig === null}
            onClick={() => setGlobalScene(null)}
          />
          {/* "添加" 单元 — 点开本地文件选择器 */}
          <button
            type="button"
            onClick={onPickFile}
            className="relative rounded-md overflow-hidden transition hover:opacity-90 focus:outline-none flex items-center justify-center"
            style={{
              aspectRatio: '16 / 10',
              border: '1px dashed var(--color-border-subtle)',
              background: 'color-mix(in srgb, var(--color-bg-elevated) 70%, transparent)',
              color: 'var(--color-text-secondary)',
            }}
            aria-label="添加背景图"
          >
            <Plus size={20} />
            <span className="ml-1 text-xs">添加</span>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,video/mp4,video/webm"
            onChange={onFileSelected}
            style={{ display: 'none' }}
          />
          {items.map((b) => {
            const url = resolveBackgroundUrl(b);
            return (
              <BackgroundTile
                key={`${b.source}:${b.path}`}
                label={b.name}
                kind={b.type}
                path={url}
                selected={currentSig === url}
                onClick={() => setGlobalScene({ type: b.type, path: url })}
                onDelete={b.source === 'user' ? () => askDelete(b) : undefined}
              />
            );
          })}
        </div>
        {items.length === 0 && !loading && !error && (
          <p
            className="text-[11px] mt-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            目录为空 · 用上面"添加"传一张,或往 backgrounds/ 放文件后点"刷新"。
          </p>
        )}
        {error && (
          <p
            className="text-[11px] mt-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            列表加载失败:{error}
          </p>
        )}
      </div>

      {/* 删除确认条(inline · 替换 window.confirm 避免 Tauri WKWebView 静默坑) */}
      {confirmDelete && (
        <div
          className="mt-3 rounded-lg p-3 flex items-center gap-3"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
            border: '1px solid var(--color-border-subtle)',
          }}
        >
          <div className="text-xs flex-1" style={{ color: 'var(--color-text-primary)' }}>
            确认删除「<span className="font-mono">{confirmDelete.name}</span>」?
            {deleteErr && (
              <span className="ml-2" style={{ color: 'var(--color-text-secondary)' }}>
                · 删除失败:{deleteErr}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={cancelDelete}
            disabled={deleting}
            className="px-3 py-1.5 text-xs rounded transition hover:opacity-80 disabled:opacity-50"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void doDelete()}
            disabled={deleting}
            className="px-3 py-1.5 text-xs rounded transition hover:opacity-80 disabled:opacity-50"
            style={{
              background: '#dc2626',
              color: '#fff',
            }}
          >
            {deleting ? '删除中…' : '确认删除'}
          </button>
        </div>
      )}

      {/* 超大预检失败时 uploadErr 提到独立行(此时 pendingFile 已 null 不进下方块) */}
      {!pendingFile && uploadErr && (
        <p
          className="mt-2 text-[11px]"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {uploadErr}
        </p>
      )}

      {/* 待上传文件 → 命名 + 提交栏 · 选了文件才显示 */}
      {pendingFile && (
        <div
          className="mt-3 rounded-lg p-3 space-y-2"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
            border: '1px solid var(--color-border-subtle)',
          }}
        >
          <div
            className="text-xs"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            待上传:<span className="font-mono">{pendingFile.name}</span>
            {' · '}
            {(pendingFile.size / (1024 * 1024)).toFixed(1)} MB
          </div>
          <input
            type="text"
            value={uploadName}
            onChange={(e) => setUploadName(e.target.value)}
            placeholder="给它起个名字(空 = 用原文件名)"
            className="w-full rounded px-2 py-1.5 text-sm outline-none focus:ring-1"
            style={{
              background: 'var(--color-bg-input)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
            }}
            autoComplete="off"
            disabled={uploading}
          />
          {uploadErr && (
            <p className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
              上传失败:{uploadErr}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={cancelUpload}
              disabled={uploading}
              className="px-3 py-1.5 text-xs rounded transition hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-primary)',
              }}
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void submitUpload()}
              disabled={uploading}
              className="px-3 py-1.5 text-xs rounded transition hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-bubble-user-text)',
              }}
            >
              {uploading ? '上传中…' : '上传'}
            </button>
          </div>
        </div>
      )}

      {/* 高级:自定义路径(折叠) */}
      <details className="mt-3">
        <summary
          className="text-xs cursor-pointer select-none"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          自定义路径(高级)
        </summary>
        <div
          className="mt-2 rounded-lg p-3 space-y-3"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-surface) 50%, transparent)',
            border: '1px solid var(--color-border-subtle)',
          }}
        >
          <div className="flex items-center gap-4 text-sm">
            <label className="flex items-center gap-1 cursor-pointer">
              <input
                type="radio"
                checked={draftType === 'image'}
                onChange={() => setDraftType('image')}
              />
              <span style={{ color: 'var(--color-text-primary)' }}>图片</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input
                type="radio"
                checked={draftType === 'video'}
                onChange={() => setDraftType('video')}
              />
              <span style={{ color: 'var(--color-text-primary)' }}>视频</span>
            </label>
          </div>
          <input
            type="text"
            value={draftPath}
            onChange={(e) => setDraftPath(e.target.value)}
            placeholder={
              draftType === 'image'
                ? '/path/to/wallpaper.jpg 或 https://…'
                : '/path/to/scene.mp4 或 https://…'
            }
            className="w-full rounded px-2 py-1.5 text-sm font-mono outline-none focus:ring-1"
            style={{
              background: 'var(--color-bg-input)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
            }}
            autoComplete="off"
          />
          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={applyDraft}
              className="px-3 py-1.5 text-xs rounded transition hover:opacity-80"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-bubble-user-text)',
              }}
            >
              应用
            </button>
          </div>
          <p
            className="text-[11px]"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            适合用 URL 或不放进 backgrounds/ 的本地路径。空字符串 = 清除全局壁纸。
          </p>
        </div>
      </details>
    </section>
  );
}

// 缩略图单元 · 120 宽自适应高(image 16:9 cover · video 同 · none 给个虚框)。
// 选中态:accent 实色边框 + 右上角小圆点(角标),保证花壁纸上仍醒目。
// onDelete 给 user 资产用:右上角加 trash chip,stopPropagation 防误触 tile select。
interface BackgroundTileProps {
  label: string;
  kind: 'image' | 'video' | 'none';
  path?: string;
  selected: boolean;
  onClick: () => void;
  onDelete?: () => void;
}
function BackgroundTile({ label, kind, path, selected, onClick, onDelete }: BackgroundTileProps) {
  return (
    <div
      className="relative rounded-md overflow-hidden transition hover:opacity-90"
      style={{
        aspectRatio: '16 / 10',
        border: selected
          ? '2px solid var(--color-accent)'
          : '1px solid var(--color-border-subtle)',
        background: 'var(--color-bg-elevated)',
      }}
    >
    <button
      type="button"
      onClick={onClick}
      className="absolute inset-0 text-left focus:outline-none"
      style={{ background: 'transparent' }}
      aria-pressed={selected}
      title={path ?? label}
    >
      {kind === 'image' && path && (
        <img
          src={path}
          alt=""
          className="absolute inset-0 w-full h-full"
          style={{ objectFit: 'cover' }}
          draggable={false}
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.opacity = '0.2';
          }}
        />
      )}
      {kind === 'video' && path && (
        <video
          key={path}
          src={path}
          autoPlay
          loop
          muted
          playsInline
          className="absolute inset-0 w-full h-full"
          style={{ objectFit: 'cover', pointerEvents: 'none' }}
        />
      )}
      {kind === 'none' && (
        <div
          className="absolute inset-0 flex items-center justify-center text-xs"
          style={{
            color: 'var(--color-text-secondary)',
            backgroundImage:
              'repeating-linear-gradient(45deg, transparent 0 6px, color-mix(in srgb, var(--color-border-subtle) 80%, transparent) 6px 7px)',
          }}
        >
          ✕ 无壁纸
        </div>
      )}
      {/* 底部 label scrim */}
      <div
        className="absolute left-0 right-0 bottom-0 px-1.5 py-1 text-[10px] truncate"
        style={{
          background: 'linear-gradient(to top, rgba(0,0,0,0.55), transparent)',
          color: '#fff',
          textShadow: '0 1px 2px rgba(0,0,0,0.6)',
        }}
      >
        {label}
        {kind === 'video' && <span className="ml-1 opacity-80">▶</span>}
      </div>
      {/* 选中角标 */}
      {selected && (
        <span
          className="absolute top-1.5 right-1.5 w-2.5 h-2.5 rounded-full"
          style={{
            background: 'var(--color-accent)',
            boxShadow: '0 0 0 2px var(--color-bg-elevated)',
          }}
          aria-hidden="true"
        />
      )}
    </button>
    {/* 删除按钮(user 资产)· 浮在 tile 之上 absolute,stopPropagation 防点穿 tile */}
    {onDelete && (
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        className="absolute top-1 left-1 p-1 rounded transition hover:opacity-90"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 80%, transparent)',
          color: 'var(--color-text-secondary)',
          border: '1px solid var(--color-border-subtle)',
        }}
        title="删除这张背景"
        aria-label="删除背景"
      >
        <Trash2 size={11} />
      </button>
    )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 关于 section
// ---------------------------------------------------------------------------

function AboutSection() {
  const [model, setModel] = useState<string>('…');

  const refreshModel = useCallback(async () => {
    // bugfix-3.3: 走 DB ai_providers,找 type='llm' 且 is_active=true 的 provider。
    // 无 active → '(none)'。
    try {
      const resp = await listProvidersByType('llm');
      for (const v of resp.vendors) {
        const active = v.providers.find((p) => p.is_active);
        if (active) {
          setModel(active.name);
          return;
        }
      }
      const ungroupedActive = resp.ungrouped.find((p) => p.is_active);
      if (ungroupedActive) {
        setModel(ungroupedActive.name);
        return;
      }
      setModel('(none)');
    } catch {
      setModel('(unknown)');
    }
  }, []);

  useEffect(() => {
    void refreshModel();
  }, [refreshModel]);

  return (
    <div className="p-6">
      <h2
        className="text-lg font-medium mb-4"
        style={{ color: 'var(--color-text-primary)' }}
      >
        ℹ 关于
      </h2>
      <div
        className="rounded-lg p-4 space-y-3 mb-4"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
          border: '1px solid var(--color-border-subtle)',
        }}
      >
        <AboutRow label="应用" value="MomoOS" />
        <AboutRow label="当前 LLM" value={model} />
        <AboutRow label="项目" value="github.com/MomoOS" mono />
      </div>
      <p
        className="text-xs"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        体验问题 / Bug 反馈通过项目 GitHub Issues 提交。
      </p>
    </div>
  );
}

function AboutRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        {label}
      </span>
      <span
        className={`text-sm ${mono ? 'font-mono' : ''}`}
        style={{ color: 'var(--color-text-primary)' }}
      >
        {value}
      </span>
    </div>
  );
}

import { useCallback, useEffect, useState } from 'react';
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
import TwoPaneShell, { type PaneSection } from '../TwoPaneShell';
import {
  fetchBackgrounds,
  type BackgroundItem,
} from '../../lib/backgrounds';
import { RefreshCw } from 'lucide-react';

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

  const currentPath = globalScene?.path ?? null;

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
        资产放 <span className="font-mono">frontend/public/backgrounds/</span>(含一级子目录),
        后缀白名单 jpg / png / webp / mp4 / webm。点缩略图即应用。
      </p>

      {/* 缩略图网格 · "无壁纸"+ 已扫描资产 */}
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
            selected={currentPath === null}
            onClick={() => setGlobalScene(null)}
          />
          {items.map((b) => (
            <BackgroundTile
              key={b.path}
              label={b.name}
              kind={b.type}
              path={b.path}
              selected={currentPath === b.path}
              onClick={() => setGlobalScene({ type: b.type, path: b.path })}
            />
          ))}
        </div>
        {items.length === 0 && !loading && !error && (
          <p
            className="text-[11px] mt-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            目录为空 · 放图片 / 视频到 backgrounds/ 再点上方"刷新"。
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
interface BackgroundTileProps {
  label: string;
  kind: 'image' | 'video' | 'none';
  path?: string;
  selected: boolean;
  onClick: () => void;
}
function BackgroundTile({ label, kind, path, selected, onClick }: BackgroundTileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative rounded-md overflow-hidden text-left transition hover:opacity-90 focus:outline-none"
      style={{
        aspectRatio: '16 / 10',
        border: selected
          ? '2px solid var(--color-accent)'
          : '1px solid var(--color-border-subtle)',
        background: 'var(--color-bg-elevated)',
      }}
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

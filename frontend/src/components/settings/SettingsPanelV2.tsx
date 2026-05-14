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
        <div className="p-6">
          <ThemeSection />
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

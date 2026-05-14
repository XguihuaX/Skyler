import { useCallback, useEffect, useState } from 'react';
import {
  Bell,
  Info,
  Keyboard,
  Palette,
  Shield,
  Users,
} from 'lucide-react';
import { fetchModels } from '../../lib/models';
import CharacterPanel from '../CharacterPanel';
import { ProactiveSection, ThemeSection } from '../SettingsPanel';
import TwoPaneShell, {
  SectionPlaceholder,
  type PaneSection,
} from '../TwoPaneShell';

/**
 * bugfix-2: ⚙ 设置 V2 (Settings V2) — "Skyler 自身行为偏好"
 *
 * 6 个 section:
 *   - 👥 角色管理   —— mount 现有 <CharacterPanel/>
 *   - ✨ 主动陪伴   —— 复用 ProactiveSection
 *   - 🎨 外观       —— 复用 ThemeSection
 *   - ⌨ 系统       —— 占位(ASR/VAD / TTS / 启动 暂留老 SettingsPanel)
 *   - 🔒 隐私 / 数据 —— 占位(Memory / Activity / Clipboard 暂留老 SettingsPanel)
 *   - ℹ 关于       —— app name + 当前 model + GitHub
 *
 * 老 SettingsPanel 不删,sidebar 上 "高级" 入口仍可访问。
 */

interface SettingsPanelV2Props {
  showToast: (text: string) => void;
}

export default function SettingsPanelV2({ showToast }: SettingsPanelV2Props) {
  const [activeId, setActiveId] = useState<string>('characters');

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
      id: 'system',
      label: '系统',
      Icon: Keyboard,
      disabled: true,
      disabledHint: '暂留在"高级"面板(ASR/VAD / TTS / 启动)',
      render: () => (
        <SectionPlaceholder
          emoji="⌨"
          title="系统"
          hint="快捷键 / 启动项 / 录音模式 / TTS 启用等。暂留在 sidebar 的 「高级」 面板,后续 Bugfix-4 + 挪过来。"
        />
      ),
    },
    {
      id: 'privacy',
      label: '隐私 / 数据',
      Icon: Shield,
      disabled: true,
      disabledHint: '暂留在"高级"面板(Memory / Activity / Clipboard)',
      render: () => (
        <SectionPlaceholder
          emoji="🔒"
          title="隐私 / 数据"
          hint="记忆管理 / 活动感知 / 剪贴板捕获 / 用户画像。暂留在 sidebar 的 「高级」 面板。"
        />
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
    <TwoPaneShell
      title="设置"
      sections={sections}
      activeId={activeId}
      onActiveChange={setActiveId}
    />
  );
}

// ---------------------------------------------------------------------------
// 关于 section —— app 信息 + 当前 LLM model
// ---------------------------------------------------------------------------

function AboutSection() {
  const [model, setModel] = useState<string>('…');

  const refreshModel = useCallback(async () => {
    try {
      const s = await fetchModels();
      const info = s.available.find((m) => m.id === s.current);
      setModel(info?.display_name ?? s.current);
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
        className="rounded-lg p-4 space-y-3"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
          border: '1px solid var(--color-border-subtle)',
        }}
      >
        <AboutRow label="应用" value="MomoOS" />
        <AboutRow label="当前 LLM" value={model} />
        <AboutRow
          label="项目"
          value="github.com/MomoOS"
          mono
        />
      </div>
      <p
        className="text-xs mt-4"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        用户体验问题 / 漏掉的设置项 → 通过 sidebar 的「高级」面板回退访问完整设置。
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

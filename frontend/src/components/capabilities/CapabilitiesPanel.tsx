import { useCallback, useEffect, useState } from 'react';
import { Brain, Plug, Sparkles, Theater, Upload } from 'lucide-react';
import {
  fetchLive2DModels,
  type Live2DModel,
  type Live2DUploadResult,
} from '../../lib/live2d';
import ExtensionsSection from '../ExtensionsSection';
import Live2DDropzone from '../live2d/Live2DDropzone';
import TwoPaneShell, {
  SectionPlaceholder,
  type PaneSection,
} from '../TwoPaneShell';

/**
 * bugfix-2: 📂 能力 (Capabilities) — "给 Skyler 装资源 / 接外部世界"
 *
 * 4 个 section:
 *   - 🔌 MCP Servers     —— 复用 ExtensionsSection
 *   - 🎭 Live2D Models   —— app 级模型库 list + dropzone(独立于 CharacterPanel)
 *   - 🧠 AI Providers    —— 占位(Bugfix-3 填)
 *   - 🧩 Skills .py      —— 占位(v4.1+)
 */

interface CapabilitiesPanelProps {
  showToast: (text: string) => void;
}

export default function CapabilitiesPanel({ showToast }: CapabilitiesPanelProps) {
  const [activeId, setActiveId] = useState<string>('mcp');

  const sections: PaneSection[] = [
    {
      id: 'mcp',
      label: 'MCP Servers',
      Icon: Plug,
      render: () => (
        <div className="p-6">
          <ExtensionsSection showToast={showToast} />
        </div>
      ),
    },
    {
      id: 'live2d',
      label: 'Live2D Models',
      Icon: Theater,
      render: () => <Live2DModelLibrary showToast={showToast} />,
    },
    {
      id: 'ai',
      label: 'AI Providers',
      Icon: Brain,
      disabled: true,
      disabledHint: '即将推出 (Bugfix-3)',
      render: () => (
        <SectionPlaceholder
          emoji="🧠"
          title="AI Providers"
          hint="多 LLM provider 管理 (添加 OpenAI / Anthropic / DeepSeek 等 key、切换默认模型)。Bugfix-3 推出。"
        />
      ),
    },
    {
      id: 'skills',
      label: 'Skills (.py)',
      Icon: Sparkles,
      disabled: true,
      disabledHint: '即将推出 v4.1+',
      render: () => (
        <SectionPlaceholder
          emoji="🧩"
          title="Skills (Python 插件)"
          hint="用户可上传 .py 文件扩展 Momo 能力 —— 类似 MCP 但更轻量。v4.1+ 推出。"
        />
      ),
    },
  ];

  return (
    <TwoPaneShell
      title="能力"
      sections={sections}
      activeId={activeId}
      onActiveChange={setActiveId}
    />
  );
}

// ---------------------------------------------------------------------------
// Live2D Models 子 section —— app 级模型库(与 CharacterPanel 内 dropdown 数据
// 共享后端,独立 UI 视角)
// ---------------------------------------------------------------------------

interface Live2DModelLibraryProps {
  showToast: (text: string) => void;
}

function Live2DModelLibrary({ showToast }: Live2DModelLibraryProps) {
  const [models, setModels] = useState<Live2DModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [showUpload, setShowUpload] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchLive2DModels();
      setModels(data.models);
    } catch (e) {
      showToast(`Live2D 模型加载失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onUploadSuccess = (result: Live2DUploadResult) => {
    setShowUpload(false);
    showToast(`已上传 ${result.slug}(${result.motions_count} 个动作)`);
    void refresh();
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2
            className="text-lg font-medium"
            style={{ color: 'var(--color-text-primary)' }}
          >
            🎭 Live2D 模型库
          </h2>
          <p
            className="text-xs mt-1"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            上传 .zip 模型包到本地 ~/.momoos/live2d/，角色编辑时下拉选用。
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            className="text-xs px-3 py-1.5 rounded-md transition"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
              opacity: loading ? 0.5 : 1,
            }}
          >
            {loading ? '…' : '↻ 刷新'}
          </button>
          <button
            type="button"
            onClick={() => setShowUpload(true)}
            className="text-xs px-3 py-1.5 rounded-md flex items-center gap-1.5 transition"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            <Upload size={14} />
            <span>上传 .zip</span>
          </button>
        </div>
      </div>

      {loading && models.length === 0 ? (
        <div
          className="text-sm py-12 text-center"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          加载中…
        </div>
      ) : models.length === 0 ? (
        <div
          className="text-sm py-12 text-center"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          还没有 Live2D 模型。点上方"上传 .zip"添加一个。
        </div>
      ) : (
        <ul className="space-y-2">
          {models.map((m) => (
            <li
              key={m.slug}
              className="rounded-lg px-4 py-3 flex items-center gap-3"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
                border: '1px solid var(--color-border-subtle)',
              }}
            >
              <div className="flex-1 min-w-0">
                <div
                  className="text-sm font-medium truncate"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  {m.slug}
                </div>
                <div
                  className="text-[11px] mt-0.5"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  {m.moc3_version_label}
                  {!m.pixi_compatible && ' · ⚠ Pixi 不兼容'}
                  {m.warnings.length > 0 && ` · ${m.warnings.length} 个警告`}
                </div>
              </div>
              <span
                className="text-[10px] px-2 py-1 rounded uppercase tracking-wide"
                style={{
                  background: m.pixi_compatible
                    ? 'rgba(16, 185, 129, 0.15)'
                    : 'rgba(245, 158, 11, 0.15)',
                  color: m.pixi_compatible
                    ? 'rgb(16, 185, 129)'
                    : 'rgb(245, 158, 11)',
                }}
              >
                {m.pixi_compatible ? 'ready' : 'check'}
              </span>
            </li>
          ))}
        </ul>
      )}

      {showUpload && (
        <Live2DDropzone
          onClose={() => setShowUpload(false)}
          onSuccess={onUploadSuccess}
        />
      )}
    </div>
  );
}

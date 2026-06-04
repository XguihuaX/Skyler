/**
 * 2026-06-05 · ② 系统状态页 — 实时仪表 + 后端 health 子状态 + 模型 active + 角色/场景/资源监控。
 *
 * 入口:Sidebar Gauge 图标 → setActiveOverlay('system') → Panel.tsx overlay。
 * 布局:2 列瀑布(grid-cols-2)+ 整页 scroll。窄窗回落单列。
 * 5 张卡:
 *   1. 🎙 语音/录音       — 全部 store 实时(VAD 间歇 bug 仪器,值要显眼)
 *   2. 🔌 连接/后端        — store 实时(WS/AI status)+ /api/health poll 5s
 *   3. 🧠 模型             — /api/ai-providers(LLM/TTS)+ /api/config/asr · 挂载拉一次 + 手动刷新
 *   4. 🎴 角色/场景        — store 实时(currentCharacter / currentCharacterState / globalScene)
 *   5. 📊 资源(救活老 SystemStatusSection)— /api/observability/system/resources poll 3s
 *
 * 纪律:没现成数据源的项一律 skip(版本号 / git SHA / WS 重连次数)。
 */
import VoiceCard       from './cards/VoiceCard';
import ConnectionCard  from './cards/ConnectionCard';
import ModelsCard      from './cards/ModelsCard';
import CharacterCard   from './cards/CharacterCard';
import ResourcesCard   from './cards/ResourcesCard';

export default function SystemPanel() {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div
        className="px-6 py-4 shrink-0 flex items-center"
        style={{
          borderBottom: '1px solid var(--color-border-subtle)',
          color: 'var(--color-text-primary)',
        }}
      >
        <h2 className="text-base font-medium">系统</h2>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <div className="grid gap-4" style={{
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        }}>
          <VoiceCard />
          <ConnectionCard />
          <ModelsCard />
          <CharacterCard />
          <ResourcesCard />
        </div>
      </div>
    </div>
  );
}

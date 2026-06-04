import { useAppStore } from '../../../store';
import Card from './Card';

const MOOD_EMOJI: Record<string, string> = {
  happy: '😊', sad: '😢', curious: '🤔', calm: '😌',
  excited: '✨', tired: '😴', neutral: '🙂',
};

// 跟 SceneSection 同款判定:bundled = 相对 path · user = backend BASE 前缀。
// 简单 startsWith 判断不依赖 BackgroundItem.source 字段(globalScene 持久化的是
// resolved URL,无 source)。
function sceneSource(path: string | null | undefined): 'bundled' | 'user' | '— 自定义路径 / URL —' {
  if (!path) return '— 自定义路径 / URL —';
  if (path.startsWith('/backgrounds/')) return 'bundled';
  if (path.includes('/userdata/backgrounds/')) return 'user';
  return '— 自定义路径 / URL —';
}

export default function CharacterCard() {
  const characters         = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const state              = useAppStore((s) => s.currentCharacterState);
  const globalScene        = useAppStore((s) => s.globalScene);

  const cur = characters.find((c) => c.id === currentCharacterId) ?? null;
  const mood = state?.mood ?? 'neutral';
  const emoji = MOOD_EMOJI[mood] ?? '🙂';

  return (
    <Card title="🎴 角色 / 场景">
      <div className="space-y-3 text-xs">
        {/* 角色 */}
        <div>
          <div style={{ color: 'var(--color-text-secondary)' }}>当前角色</div>
          <div className="mt-0.5" style={{ color: 'var(--color-text-primary)' }}>
            {cur ? (
              <>
                <span className="font-medium">{cur.name}</span>
                <span className="font-mono ml-2 text-[10px]"
                  style={{ color: 'var(--color-text-secondary)' }}>
                  id={cur.id}
                </span>
              </>
            ) : (
              <span style={{ color: 'var(--color-text-secondary)' }}>— 无 —</span>
            )}
          </div>
        </div>

        {/* 心情 + 亲密度 */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div style={{ color: 'var(--color-text-secondary)' }}>心情</div>
            <div className="mt-0.5" style={{ color: 'var(--color-text-primary)' }}>
              <span className="mr-1">{emoji}</span>{mood}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--color-text-secondary)' }}>亲密度</div>
            <div className="font-mono tabular-nums mt-0.5"
              style={{ color: 'var(--color-text-primary)' }}>
              {state?.intimacy ?? '—'} / 100
            </div>
          </div>
        </div>

        {/* thought / activity (闲笔) */}
        {(state?.thought || state?.activity) && (
          <div
            className="pt-2 mt-1 space-y-1 text-[11px]"
            style={{
              borderTop: '1px dashed var(--color-border-subtle)',
              color: 'var(--color-text-secondary)',
            }}
          >
            {state.activity && <div>📍 {state.activity}</div>}
            {state.thought  && <div>💭 {state.thought}</div>}
          </div>
        )}

        {/* 当前壁纸 */}
        <div
          className="pt-2 mt-1"
          style={{ borderTop: '1px dashed var(--color-border-subtle)' }}
        >
          <div style={{ color: 'var(--color-text-secondary)' }}>当前壁纸</div>
          {globalScene ? (
            <div className="mt-0.5 space-y-0.5">
              <div className="font-mono text-[10px] break-all"
                style={{ color: 'var(--color-text-primary)' }}>
                {globalScene.path}
              </div>
              <div className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
                {globalScene.type} · {sceneSource(globalScene.path)}
              </div>
            </div>
          ) : (
            <div className="mt-0.5 text-[11px]"
              style={{ color: 'var(--color-text-secondary)' }}>
              — 未设置(主题色作底)—
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

/**
 * 2026-06-02 · UI redesign step 1 · 全局场景背景层(壁纸,跨角色共享)。
 * 2026-06-03 · Round 3 重构:per-character background_path 渲染从 CharacterView
 * 迁入这里,SceneBackground 成为整窗壁纸的**唯一**渲染层。
 *
 * 挂载位置:Panel.tsx 容器内 z-0(整个 Panel 之下) · 不挂 Widget(小窗暂不动)。
 *
 * 数据优先级(effective scene):
 *   1. 当前角色的 background_path(per-character bg)— 后缀合法且加载成功
 *   2. store.globalScene(全局壁纸,跨角色)
 *   3. 都没 → 不渲染,Panel 容器 bg-base 兜底色透出
 *
 * 关键差异(老版本):老 character bg 挂在 CharacterView 内 absolute inset-0,只
 * 覆盖 chat main area(paddingLeft:80 之后的区域)且被 character wrapper
 * translateX(-17%) 左移 → 左右出现"没壁纸"的色阶断层。迁入这里后,无论
 * per-character 还是 globalScene,都画在整窗 z-0 层,真正 edge-to-edge。
 *
 * 视频:autoPlay/loop/muted/playsInline,失败 silent + onError 静默降级(per-
 * character 失败 → globalScene · globalScene 失败 → 不渲染)。
 */
import { useState, useEffect } from 'react';
import { useAppStore } from '../store';

// 后缀分类(从 CharacterView 迁过来 · 跟 backend/services/backgrounds_scanner.py
// 同白名单 · lowercase 后比较 · 前端按后缀分发到 <img> / <video>)。
const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const VIDEO_EXTS = new Set(['.mp4', '.webm']);

function classifyBackground(path: string | null | undefined): 'image' | 'video' | null {
  if (!path) return null;
  const trimmed = path.trim();
  if (!trimmed) return null;
  const dotIdx = trimmed.lastIndexOf('.');
  if (dotIdx === -1) return null;
  const ext = trimmed.slice(dotIdx).toLowerCase();
  if (IMAGE_EXTS.has(ext)) return 'image';
  if (VIDEO_EXTS.has(ext)) return 'video';
  return null;
}

export default function SceneBackground() {
  const globalScene        = useAppStore((s) => s.globalScene);
  const characters         = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);

  // per-character bg 失败 → 静默降级到 globalScene;globalScene 失败 → 不渲染。
  // 两路失败状态独立,切换角色或 path 时各自 reset。
  const [charBgFailed, setCharBgFailed]     = useState(false);
  const [globalBgFailed, setGlobalBgFailed] = useState(false);

  const currentCharacter =
    characters.find((c) => c.id === currentCharacterId) ?? null;
  const charBgPath = currentCharacter?.background_path ?? null;
  const charBgKind = charBgFailed ? null : classifyBackground(charBgPath);

  useEffect(() => {
    setCharBgFailed(false);
  }, [currentCharacterId, charBgPath]);

  useEffect(() => {
    setGlobalBgFailed(false);
  }, [globalScene?.path]);

  // effective scene:per-character bg 优先,没有再降到 globalScene。
  type Resolved = { kind: 'character' | 'global'; type: 'image' | 'video'; path: string };
  let effective: Resolved | null = null;
  if (charBgKind && charBgPath) {
    effective = { kind: 'character', type: charBgKind, path: charBgPath };
  } else if (globalScene && !globalBgFailed) {
    effective = { kind: 'global', type: globalScene.type, path: globalScene.path };
  }

  if (!effective) return null;

  // img/video 显式 absolute inset-0 + width/height 100% inline style(不依赖
  // Tailwind w-full h-full,某些嵌套下 100% 可能拿不到 wrapper 真实尺寸 ·
  // cover 后留白)。
  const mediaStyle: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    objectPosition: 'center center',
    userSelect: 'none',
    pointerEvents: 'none',
  };

  const onError = effective.kind === 'character'
    ? () => setCharBgFailed(true)
    : () => setGlobalBgFailed(true);

  return (
    <div
      className="pointer-events-none overflow-hidden"
      aria-hidden="true"
      style={{
        // absolute inset-0 锚 Panel 根容器(relative + w-full h-full = viewport
        // 尺寸)· 跟 Panel 容器 resize 一起自动重布局 · 不用 fixed 避免任意祖先
        // transform/filter/will-change 创建 containing block 让 fixed 错锚。
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 0,
      }}
    >
      {effective.type === 'image' ? (
        <img
          src={effective.path}
          alt=""
          draggable={false}
          style={mediaStyle}
          onError={onError}
        />
      ) : (
        <video
          key={effective.path}
          src={effective.path}
          autoPlay
          loop
          muted
          playsInline
          style={mediaStyle}
          onError={onError}
        />
      )}
    </div>
  );
}

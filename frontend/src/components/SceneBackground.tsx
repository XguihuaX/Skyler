/**
 * 2026-06-02 · UI redesign step 1 · 全局场景背景层(壁纸,跨角色共享)。
 * 2026-06-03 · Round 3 重构:per-character background_path 渲染也搬过这里。
 * 2026-06-04 · Round 5 step1 解耦:撤掉 per-character bg 这一路,SceneBackground
 * 只消费 globalScene。切角色绝不再换壁纸,壁纸 100% 走全局设置(SceneSection)。
 * character.background_path DB 列 + 模型 + form 字段保留 dormant(tech debt:
 * 以后做"每角色默认 + 全局覆盖"混合档再启用)。
 *
 * 挂载位置:Panel.tsx 容器内 z-0(整个 Panel 之下) · 不挂 Widget。
 *
 * 渲染:globalScene 加载成功 → img / video edge-to-edge cover · 失败或未设
 * → 不渲染,Panel bg-base 兜底色透出。
 */
import { useState, useEffect } from 'react';
import { useAppStore } from '../store';

export default function SceneBackground() {
  const scene = useAppStore((s) => s.globalScene);
  const [failed, setFailed] = useState(false);

  // 切 path 时 reset 失败标志(避免上一资源 fail 残留)
  useEffect(() => {
    setFailed(false);
  }, [scene?.path]);

  if (!scene || failed) return null;

  // img/video 显式 absolute inset-0 + width/height 100% inline style(不依赖
  // Tailwind w-full h-full,某些嵌套下 100% 可能拿不到 wrapper 真实尺寸)。
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
      {scene.type === 'image' ? (
        <img
          src={scene.path}
          alt=""
          draggable={false}
          style={mediaStyle}
          onError={() => setFailed(true)}
        />
      ) : (
        <video
          key={scene.path}
          src={scene.path}
          autoPlay
          loop
          muted
          playsInline
          style={mediaStyle}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}

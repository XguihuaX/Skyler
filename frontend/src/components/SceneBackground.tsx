/**
 * 2026-06-02 · UI redesign step 1 · 全局场景背景层(壁纸,跨角色共享)。
 *
 * 挂载位置:Panel.tsx 容器内 z-0(整个 Panel 之下) · 不挂 Widget(小窗暂不动)。
 *
 * 跟 CharacterView.tsx 现有 character.background_path 的关系:
 *   - character bg 是 per-character、挂在 CharacterView 内 z-0(chat 主区那块)
 *   - SceneBackground 是 app 级、挂 Panel 容器 z-0(整窗,含 Sidebar / ConvList /
 *     ChatHistoryPanel 之下)
 *   - character bg 设了 → 在 CharacterView 区域覆盖 SceneBackground
 *   - character bg 没设 → CharacterView 区域透出 SceneBackground
 *   - 全 panel 范围共享 SceneBackground · 主题切换不动它
 *
 * 数据来源:store.globalScene · localStorage 持久化 · 由
 * SettingsPanelV2 → SceneSection 写入。
 *
 * 视频:autoPlay/loop/muted/playsInline,失败 silent(onError 不切换占位,
 * 显示透明 div)。
 */
import { useState, useEffect } from 'react';
import { useAppStore } from '../store';

export default function SceneBackground() {
  const scene = useAppStore((s) => s.globalScene);
  const [failed, setFailed] = useState(false);

  // 切换路径时 reset 失败标志(避免上一个失败的资源残留 fail 状态)
  useEffect(() => {
    setFailed(false);
  }, [scene?.path]);

  if (!scene || failed) return null;

  const commonStyle: React.CSSProperties = {
    objectFit: 'cover',
    objectPosition: 'center center',
    userSelect: 'none',
    pointerEvents: 'none',
  };

  return (
    <div
      className="absolute inset-0 z-0 pointer-events-none overflow-hidden"
      aria-hidden="true"
    >
      {scene.type === 'image' ? (
        <img
          src={scene.path}
          alt=""
          className="w-full h-full select-none"
          draggable={false}
          style={commonStyle}
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
          className="w-full h-full"
          style={commonStyle}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}

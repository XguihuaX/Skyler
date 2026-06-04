import { useState } from 'react';
import characterImg from '../assets/character.jpeg';
import { useAppStore } from '../store';
import { resolveLive2dModelUrl } from '../config/live2d';
import Live2DCanvas from './Live2DCanvas';

interface CharacterViewProps {
  modelUrl?: string;
  expression?: string;
  motion?: string;
  className?: string;
}

// 2026-06-03 · Round 3 壁纸统一:per-character background_path 渲染下沉到
// SceneBackground(全窗 z-0 层),CharacterView 不再画任何背景层 — 只渲染
// Live2D 或 fallback 静态角色图(角色本身,不是壁纸)。原 v3.5 chunk 5a 的
// backgroundLayer + bgFailed state + classifyBackground / IMAGE_EXTS /
// VIDEO_EXTS 工具一并迁移到 SceneBackground.tsx · 数据来源仍是
// currentCharacter.background_path · 不动 store · 不动设置 UI。

export default function CharacterView({
  modelUrl: _modelUrl,
  expression: _expression,
  motion: _motion,
  className,
}: CharacterViewProps) {
  const [imgError, setImgError]   = useState(false);

  const mode               = useAppStore((s) => s.mode);
  const characters         = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  // v3-E2 patch:scanner 结果作为主数据源传给 resolveLive2dModelUrl,
  // hardcode 字典退为兜底(store 空时仍能解析 hiyori)。
  const live2dModels       = useAppStore((s) => s.live2dModels);

  const currentCharacter =
    characters.find((c) => c.id === currentCharacterId) ?? null;
  const live2dUrl = resolveLive2dModelUrl(
    currentCharacter?.live2d_model,
    live2dModels,
  );

  const isPanel = mode === 'panel';
  const rootClass = className ?? 'absolute inset-0';

  // 角色配了 live2d_model 且能解析出资源 URL → 走 Live2D 渲染管道
  // key 用 live2dUrl,切换角色时强制 unmount 旧 canvas + mount 新的
  if (live2dUrl) {
    return (
      <div className={rootClass}>
        {/* Live2D canvas · 背景层已下沉到全窗 SceneBackground · 这里只角色透明 */}
        <div className="absolute inset-0 z-10">
          <Live2DCanvas key={live2dUrl} modelUrl={live2dUrl} />
        </div>
      </div>
    );
  }

  // Fallback:保留 v3-E1 之前的静态角色图(适用于尚未配置 live2d_model 的角色)。
  // 2026-06-03 · Round 3:per-character background_path 已迁出到 SceneBackground,
  // 这里不再有 backgroundLayer + !bgKind gate · 直接渲染静态角色 jpeg / fallback svg。
  return (
    <div className={rootClass}>
      {imgError ? (
        <div
          className="w-full h-full flex flex-col items-center justify-center relative z-10"
          style={{ color: 'var(--color-text-accent)' }}
        >
          <svg
            width="120"
            height="160"
            viewBox="0 0 120 160"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            style={{ opacity: 0.5 }}
          >
            <defs>
              <linearGradient id="headGrad" x1="32" y1="12" x2="88" y2="68" gradientUnits="userSpaceOnUse">
                <stop stopColor="currentColor" />
                <stop offset="1" stopColor="currentColor" stopOpacity="0.6" />
              </linearGradient>
              <linearGradient id="bodyGrad" x1="20" y1="80" x2="100" y2="150" gradientUnits="userSpaceOnUse">
                <stop stopColor="currentColor" />
                <stop offset="1" stopColor="currentColor" stopOpacity="0.4" />
              </linearGradient>
            </defs>
            {/* Head */}
            <circle cx="60" cy="40" r="28" stroke="url(#headGrad)" strokeWidth="2" fill="none" />
            {/* Neck */}
            <rect x="50" y="67" width="20" height="14" stroke="url(#bodyGrad)" strokeWidth="2" fill="none" />
            {/* Body (trapezoid) */}
            <path d="M30 81 L18 150 L102 150 L90 81 Z" stroke="url(#bodyGrad)" strokeWidth="2" fill="none" />
          </svg>
          <span
            className="text-sm font-medium mt-2"
            style={{ color: 'var(--color-text-secondary)', opacity: 0.6 }}
          >
            Momo
          </span>
        </div>
      ) : (
        <img
          src={characterImg}
          alt="Momo"
          className="w-full h-full select-none relative z-10"
          draggable={false}
          onDragStart={(e) => e.preventDefault()}
          style={{
            objectFit: isPanel ? 'contain' : 'cover',
            objectPosition: isPanel ? 'center center' : 'center top',
            userSelect: 'none',
            ...({ WebkitUserDrag: 'none' } as unknown as React.CSSProperties),
          }}
          onError={() => setImgError(true)}
        />
      )}
    </div>
  );
}

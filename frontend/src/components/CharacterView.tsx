import { useState, useEffect } from 'react';
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

// v3.5 chunk 5a：后缀分类，与 backend/services/backgrounds_scanner.py 同
// 白名单（lowercase 后比较），前端无需后端 type 字段也能独立分发。
const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const VIDEO_EXTS = new Set(['.mp4', '.webm']);

function classifyBackground(path: string | null | undefined): 'image' | 'video' | null {
  if (!path) return null;
  const trimmed = path.trim();
  if (!trimmed) return null;
  // 取最后一个 ``.`` 之后
  const dotIdx = trimmed.lastIndexOf('.');
  if (dotIdx === -1) return null;
  const ext = trimmed.slice(dotIdx).toLowerCase();
  if (IMAGE_EXTS.has(ext)) return 'image';
  if (VIDEO_EXTS.has(ext)) return 'video';
  return null;
}

export default function CharacterView({
  modelUrl: _modelUrl,
  expression: _expression,
  motion: _motion,
  className,
}: CharacterViewProps) {
  const [imgError, setImgError]   = useState(false);
  // v3.5 chunk 5a：背景层（image / video）加载失败 → 静默降回原 fallback。
  // 切角色时 reset，否则一个角色失败会把下个角色也兜底掉。
  const [bgFailed, setBgFailed]   = useState(false);

  const mode               = useAppStore((s) => s.mode);
  const characters         = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  // v3-E2 patch：scanner 结果作为主数据源传给 resolveLive2dModelUrl，
  // hardcode 字典退为兜底（store 空时仍能解析 hiyori）。
  const live2dModels       = useAppStore((s) => s.live2dModels);

  const currentCharacter =
    characters.find((c) => c.id === currentCharacterId) ?? null;
  const live2dUrl = resolveLive2dModelUrl(
    currentCharacter?.live2d_model,
    live2dModels,
  );

  // 切角色时把 bgFailed reset，防止上一角色的 onError 状态影响下一角色
  useEffect(() => {
    setBgFailed(false);
  }, [currentCharacterId, currentCharacter?.background_path]);

  const isPanel = mode === 'panel';
  // panel 模式下加一层半透明背景叠加，使前景气泡更易读
  const panelOverlayStyle: React.CSSProperties | undefined = isPanel
    ? { background: 'color-mix(in srgb, var(--color-bg-base) 40%, transparent)' }
    : undefined;
  const rootClass = className ?? 'absolute inset-0';

  // v3.5 chunk 5a：背景层。``background_path`` 配置 + 后缀合法 + 没失败 → 渲染；
  // 失败或未配置 → 不渲染，让下层 Live2D / 静态 jpeg 走原 fallback。
  const bgPath = currentCharacter?.background_path ?? null;
  const bgKind = bgFailed ? null : classifyBackground(bgPath);
  const backgroundLayer = bgKind ? (
    <div className="absolute inset-0 z-0 pointer-events-none" aria-hidden="true">
      {bgKind === 'image' ? (
        <img
          src={bgPath!}
          alt=""
          className="w-full h-full select-none"
          draggable={false}
          style={{
            objectFit: 'cover',
            objectPosition: 'center center',
            userSelect: 'none',
          }}
          onError={() => setBgFailed(true)}
        />
      ) : (
        <video
          key={bgPath!}
          src={bgPath!}
          autoPlay
          loop
          muted
          playsInline
          className="w-full h-full"
          style={{
            objectFit: 'cover',
            objectPosition: 'center center',
            pointerEvents: 'none',
          }}
          onError={() => setBgFailed(true)}
        />
      )}
    </div>
  ) : null;

  // 角色配了 live2d_model 且能解析出资源 URL → 走 Live2D 渲染管道
  // key 用 live2dUrl，切换角色时强制 unmount 旧 canvas + mount 新的
  if (live2dUrl) {
    return (
      <div className={rootClass} style={panelOverlayStyle}>
        {backgroundLayer}
        {/* Live2D canvas 在背景层之上，z-index 显式指定 */}
        <div className="absolute inset-0 z-10">
          <Live2DCanvas key={live2dUrl} modelUrl={live2dUrl} />
        </div>
      </div>
    );
  }

  // Fallback：保留 v3-E1 之前的静态图片显示（适用于尚未配置 live2d_model 的角色）。
  // v3.5 chunk 5a：如果 background_path 有效，则 backgroundLayer 已渲染，
  // 不再叠加静态 jpeg —— 用户既然配了 per-character 背景就应该看到它。
  return (
    <div className={rootClass} style={panelOverlayStyle}>
      {backgroundLayer}
      {!bgKind && (imgError ? (
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
      ))}
    </div>
  );
}

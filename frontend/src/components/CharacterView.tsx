import { useState } from 'react';
import characterImg from '../assets/character.jpeg';
import { useAppStore } from '../store';

interface CharacterViewProps {
  modelUrl?: string;
  expression?: string;
  motion?: string;
  className?: string;
}

export default function CharacterView({
  modelUrl: _modelUrl,
  expression: _expression,
  motion: _motion,
  className,
}: CharacterViewProps) {
  const [imgError, setImgError] = useState(false);
  const mode = useAppStore((s) => s.mode);

  const isPanel = mode === 'panel';
  // panel 模式下加一层半透明背景叠加，使前景气泡更易读
  const panelOverlayStyle: React.CSSProperties | undefined = isPanel
    ? { background: 'color-mix(in srgb, var(--color-bg-base) 40%, transparent)' }
    : undefined;
  const rootClass = className ?? 'absolute inset-0';

  return (
    <div className={rootClass} style={panelOverlayStyle}>
      {imgError ? (
        <div
          className="w-full h-full flex flex-col items-center justify-center"
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
          className="w-full h-full select-none"
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

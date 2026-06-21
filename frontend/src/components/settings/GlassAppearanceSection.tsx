/**
 * 玻璃外观自定义 section(2026-06-20)。
 *
 * 控件:
 *   - iro.js 色环 → 卡面色(纯 RGB,alpha 走单独滑块)
 *   - 卡面不透明度 slider → bgAlpha
 *   - 文字对比 slider(单个)→ 同时驱动 textAlpha + textMutedAlpha
 *     (muted = primary × 0.787 · 在 applyGlassCustom 里算)
 *   - [✓ 启用自定义] 复选 · off = removeProperty 全部回主题默认
 *   - [⟲ 恢复默认] · LS.removeItem + state reset + removeProperty
 *
 * 应用层:applyGlassCustom(@ store/index.ts)按卡面亮度自动反色(浅卡面 →
 * 深字 + 淡白字阴影;深卡面 → 浅字 + 深字阴影)。
 *
 * 范式:照 ThemeSection(@ SettingsPanelLegacy.tsx:1273-1333) /
 * SceneSection(@ SettingsPanelV2.tsx)的 section 容器壳。
 */
import { useEffect, useRef } from 'react';
import { RotateCcw } from 'lucide-react';
import iro from '@jaames/iro';
import { useAppStore, type GlassCustom } from '../../store';

// 启用后未调整时的初始观感:白色卡面(亮度高 → 自动选深字)+ 50% 不透明 + 0.94 主文字对比
const DEFAULT_CUSTOM: GlassCustom = {
  enabled: true,
  r: 255, g: 255, b: 255,
  bgAlpha: 0.5,
  textAlpha: 0.94,
};

export default function GlassAppearanceSection() {
  const glassCustom = useAppStore((s) => s.glassCustom);
  const setGlassCustom = useAppStore((s) => s.setGlassCustom);

  // 显示用值:未启用时也要拿一个值喂控件(空骨架则用 DEFAULT_CUSTOM)
  const current: GlassCustom = glassCustom ?? DEFAULT_CUSTOM;
  const enabled: boolean = glassCustom?.enabled ?? false;

  const wheelHostRef = useRef<HTMLDivElement | null>(null);
  // iro 的 ColorPicker 实例 · 5.5.2 dist 的 types 走 iro.ColorPicker(...)
  // 返回 IroColorPicker · 我们只用 .color.set 和 .on('color:change',...)
  const wheelRef = useRef<ReturnType<typeof iro.ColorPicker> | null>(null);

  // 防 onChange 反向同步抖动:setGlassCustom 触发 React re-render → useEffect
  // [r,g,b] 又调 wheel.color.set → 再触发 'color:change' → 死循环。用 ref
  // 标记"程序化 set"忽略一次 emit。
  const programmaticSetRef = useRef(false);

  // iro wheel 初始化(一次性 · 后续更新走 color.set)
  useEffect(() => {
    if (!wheelHostRef.current) return;
    const cp = iro.ColorPicker(wheelHostRef.current, {
      width: 180,
      color: `rgb(${current.r}, ${current.g}, ${current.b})`,
      layout: [{ component: iro.ui.Wheel, options: {} }],
      borderWidth: 1,
      borderColor: '#888',
    });
    // 命名 handler 让 off() 能解绑(iro.off 要 callback ref · 不能省略)
    const onColorChange = (color: iro.Color) => {
      if (programmaticSetRef.current) {
        programmaticSetRef.current = false;
        return;
      }
      const { r, g, b } = color.rgb;
      // 拖色环视为"用户在调" → 自动 enabled=true
      const base = useAppStore.getState().glassCustom ?? DEFAULT_CUSTOM;
      useAppStore.getState().setGlassCustom({
        ...base, enabled: true, r, g, b,
      });
    };
    cp.on('color:change', onColorChange);
    wheelRef.current = cp;
    return () => {
      try { cp.off('color:change', onColorChange); } catch { /* ignore */ }
      try { wheelHostRef.current?.replaceChildren(); } catch { /* ignore */ }
      wheelRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 外部 state 变了(如点恢复默认)→ 同步 wheel 显示(标记 programmatic 防回弹)
  useEffect(() => {
    const cp = wheelRef.current;
    if (!cp) return;
    try {
      programmaticSetRef.current = true;
      cp.color.set(`rgb(${current.r}, ${current.g}, ${current.b})`);
    } catch { /* ignore */ }
  }, [current.r, current.g, current.b]);

  const onToggleEnabled = (next: boolean) => {
    setGlassCustom({ ...current, enabled: next });
  };

  const onChangeBgAlpha = (v: number) => {
    setGlassCustom({ ...current, enabled: true, bgAlpha: v });
  };

  const onChangeTextAlpha = (v: number) => {
    setGlassCustom({ ...current, enabled: true, textAlpha: v });
  };

  const onReset = () => {
    setGlassCustom(null);
    // wheel 显示回到 DEFAULT_CUSTOM 的色(下次启用时初始值)
    const cp = wheelRef.current;
    if (cp) {
      try {
        programmaticSetRef.current = true;
        cp.color.set(`rgb(${DEFAULT_CUSTOM.r}, ${DEFAULT_CUSTOM.g}, ${DEFAULT_CUSTOM.b})`);
      } catch { /* ignore */ }
    }
  };

  return (
    <section
      className="mb-4 rounded-lg p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        border: '1px solid var(--color-border-subtle)',
      }}
    >
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <h3
          className="text-sm font-medium"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          玻璃外观
        </h3>
        <div className="flex items-center gap-3">
          <label className="text-xs inline-flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => onToggleEnabled(e.target.checked)}
            />
            <span style={{ color: 'var(--color-text-primary)' }}>启用自定义</span>
          </label>
          <button
            type="button"
            onClick={onReset}
            className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
            }}
            title="清除自定义,回到当前主题默认(--glass-bg 恢复 color-mix 自适应)"
          >
            <RotateCcw size={11} />
            恢复默认
          </button>
        </div>
      </div>

      <p
        className="text-[11px] mb-4"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        全局覆盖玻璃浮件外观 · 叠在当前主题之上 · 切主题不丢 · 文字色按卡面亮度自动反色(浅卡面 → 深字 / 深卡面 → 浅字)。
      </p>

      <div className="flex gap-5 items-start flex-wrap">
        {/* 色环宿主 · iro 直接接管 DOM · 禁用时半透 + pointer-events: none */}
        <div
          ref={wheelHostRef}
          style={{
            opacity: enabled ? 1 : 0.4,
            pointerEvents: enabled ? 'auto' : 'none',
          }}
        />

        {/* 滑块组 */}
        <div className="flex-1 min-w-[180px] space-y-3">
          <SliderRow
            label="卡面不透明度"
            value={current.bgAlpha}
            min={0} max={1} step={0.01}
            display={`${Math.round(current.bgAlpha * 100)}%`}
            disabled={!enabled}
            onChange={onChangeBgAlpha}
          />
          <SliderRow
            label="文字对比"
            value={current.textAlpha}
            min={0.3} max={1} step={0.01}
            display={`${Math.round(current.textAlpha * 100)}%`}
            disabled={!enabled}
            onChange={onChangeTextAlpha}
            hint="同步驱动副文字(主 × 0.787)"
          />
        </div>
      </div>
    </section>
  );
}


function SliderRow({
  label, value, min, max, step, display, disabled, onChange, hint,
}: {
  label: string;
  value: number;
  min: number; max: number; step: number;
  display: string;
  disabled: boolean;
  onChange: (v: number) => void;
  hint?: string;
}) {
  return (
    <div style={{ opacity: disabled ? 0.5 : 1 }}>
      <div className="flex items-baseline justify-between text-xs mb-1 gap-2">
        <span style={{ color: 'var(--color-text-primary)' }}>
          {label}
          {hint && (
            <span
              className="text-[10px] ml-1.5"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              · {hint}
            </span>
          )}
        </span>
        <span
          className="text-[11px] font-mono"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {display}
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full"
        style={{ accentColor: 'var(--color-accent)' }}
      />
    </div>
  );
}

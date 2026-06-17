// 2026-06-16 INV · Live2D 管理组件容器 · 模块①取景(framing)。
//
// scope = **当前模型 slug**(= character.live2d_model)· 不绑 character.id。
// 共用 slug 的角色共享 framing(预期)· 不同 slug 各自一份。
//
// 容器结构:
//   - 标题 "Live2D 管理 · {slug}"
//   - Section 1 取景(本期):scale 滑块+数字 / X/Y offset 数字 / 重置 / 保存
//   - Section 2 留位(将来 param_map)· 占位注释 不渲染
//   - Section 3 留位(将来 director)· 占位注释 不渲染
//
// 实时预览:任何控件改 framing → 立即 setPendingFraming → Live2DCanvas 监听
// pending 调 runtime.setFraming · "保存"只入 DB(PATCH model_key)。
//
// 调整模式:section 展开 → setLive2dAdjustMode(true) → Live2DCanvas 主画布
// 拖拽改 offset / 滚轮改 scale / onClick skip touch。section 收起 / unmount
// → setLive2dAdjustMode(false) 回原 touch 路径。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Save, RotateCcw, ChevronDown, ChevronRight } from 'lucide-react';
import { useAppStore } from '../../store';
import {
  DEFAULT_FRAMING,
  FRAMING_SCALE_MIN,
  FRAMING_SCALE_MAX,
  FRAMING_SCALE_STEP,
  FRAMING_OFFSET_MIN,
  FRAMING_OFFSET_MAX,
  clampFraming,
  fetchLive2DSettings,
  framingEqual,
  patchLive2DFraming,
  type Live2DFraming,
} from '../../lib/live2d/settings';

interface Live2DManagerSectionProps {
  /** 当前角色的 live2d_model slug · null/'' = 不渲染 section */
  modelKey: string | null | undefined;
  /** toast 反馈 · 跟 CharacterPanel 已有 showToast 一致风格 */
  showToast?: (text: string) => void;
}

export default function Live2DManagerSection({
  modelKey,
  showToast,
}: Live2DManagerSectionProps) {
  const [expanded, setExpanded] = useState(false);
  // server 当前值(保存后同步) · 用于 dirty 判断 + 重置兜底
  const [serverFraming, setServerFraming] =
    useState<Live2DFraming>(DEFAULT_FRAMING);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // 2026-06-17 · 数字 input 本地 text state · controlled 数字会把空串强制
  // 回 0(前导 0 删不掉、清空弹回)· 改本地 text + editing ref:
  //   - value={text};onChange:setText(v) + 解析数字喂 setPendingFraming
  //   - 用户没 focus 时 useEffect 把外部 display 值 sync 进 text(拖拽 /
  //     滑块 / 重置 / fetch 都能联动)
  //   - onBlur 归一化:setText(String(round(display)))(被 clamp 后的真值)
  const [xText, setXText] = useState('0');
  const [yText, setYText] = useState('0');
  const xEditingRef = useRef(false);
  const yEditingRef = useRef(false);

  const pendingFraming = useAppStore((s) => s.pendingFraming);
  const setPendingFraming = useAppStore((s) => s.setPendingFraming);
  const setSavedFraming = useAppStore((s) => s.setSavedFraming);
  const setLive2dAdjustMode = useAppStore((s) => s.setLive2dAdjustMode);

  // 当前显示值:pending 优先(用户调中)· null 回退 server
  const display = pendingFraming ?? serverFraming;
  const dirty = pendingFraming !== null && !framingEqual(pendingFraming, serverFraming);

  // editing 中不盖用户输入 · 否则把外部最新真值(拖拽 / 滑块 / 重置 / fetch)
  // 同步进 text。Math.round 跟 input value 的展示精度一致。
  useEffect(() => {
    if (!xEditingRef.current) setXText(String(Math.round(display.offsetX)));
  }, [display.offsetX]);
  useEffect(() => {
    if (!yEditingRef.current) setYText(String(Math.round(display.offsetY)));
  }, [display.offsetY]);

  // section 展开 / 收起 / unmount → 切 adjustMode
  useEffect(() => {
    setLive2dAdjustMode(expanded);
    return () => {
      setLive2dAdjustMode(false);
    };
  }, [expanded, setLive2dAdjustMode]);

  // 切 modelKey / 首次展开 → fetch · pending 同步清(防上一模型 dirty 残留)·
  // 同步 saved 写 store(Canvas fallback 源 · 防保存后 stale 回退,bisect 修)。
  const loadedKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!modelKey) return;
    if (loadedKeyRef.current === modelKey) return;
    loadedKeyRef.current = modelKey;
    setLoading(true);
    setPendingFraming(null);
    void fetchLive2DSettings(modelKey)
      .then((s) => {
        const clamped = clampFraming(s.framing);
        setServerFraming(clamped);
        setSavedFraming({ modelKey, framing: clamped });
      })
      .catch((err) => {
        console.warn('[Live2DManagerSection] fetch failed', err);
        setServerFraming(DEFAULT_FRAMING);
      })
      .finally(() => setLoading(false));
  }, [modelKey, setPendingFraming, setSavedFraming]);

  const updateField = useCallback((patch: Partial<Live2DFraming>) => {
    const next = clampFraming({ ...display, ...patch });
    setPendingFraming(next);
  }, [display, setPendingFraming]);

  const onReset = useCallback(() => {
    setPendingFraming({ ...DEFAULT_FRAMING });
  }, [setPendingFraming]);

  const onSave = useCallback(async () => {
    if (!modelKey || pendingFraming === null) return;
    setSaving(true);
    try {
      const s = await patchLive2DFraming(modelKey, pendingFraming);
      const clamped = clampFraming(s.framing);
      setServerFraming(clamped);
      // bisect 修:保存后**先**写 store.savedFraming · **再**清 pending。
      // 顺序很关键:清 pending 触发 Canvas useEffect [pendingFraming,
      // fallbackFraming] 时 fallback 已经是新值 · 不会闪回 stale 值。
      setSavedFraming({ modelKey, framing: clamped });
      setPendingFraming(null);
      showToast?.(`已保存 ${modelKey} 的取景`);
    } catch (err) {
      showToast?.(`保存失败:${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  }, [modelKey, pendingFraming, setPendingFraming, setSavedFraming, showToast]);

  // 留位 section 2/3 · 暂不渲染:
  // {/* TODO param_map(模块②)· 同容器 · 共享 modelKey */}
  // {/* TODO director(模块③)· 同容器 · 共享 modelKey */}

  const titleText = useMemo(
    () => modelKey ? `Live2D 管理 · ${modelKey}` : null,
    [modelKey],
  );

  if (!modelKey || !titleText) return null;

  return (
    <div
      className="mt-3 rounded-md"
      style={{
        background: 'var(--color-bg-elevated)',
        border: '1px solid var(--color-border)',
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs"
        style={{ color: 'var(--color-text-primary)' }}
      >
        <span className="flex items-center gap-1">
          {expanded
            ? <ChevronDown size={12} />
            : <ChevronRight size={12} />}
          {titleText}
        </span>
        {dirty && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded"
            style={{
              background: 'rgb(234, 179, 8)',
              color: 'rgb(0, 0, 0)',
            }}
          >
            未保存
          </span>
        )}
      </button>

      {expanded && (
        <div
          className="px-3 pb-3 space-y-3"
          style={{ borderTop: '1px solid var(--color-border)' }}
        >
          <div className="text-[10px] pt-2"
               style={{ color: 'var(--color-text-secondary)' }}>
            主画布拖拽改位置 · 滚轮改缩放 · 实时预览 · 保存后入库
          </div>

          {/* Section 1 · 取景 */}
          <div className="space-y-2">
            <div className="text-[10px] font-medium"
                 style={{ color: 'var(--color-text-secondary)' }}>
              取景
            </div>

            {/* scale */}
            <div>
              <div className="flex justify-between text-[10px] mb-1"
                   style={{ color: 'var(--color-text-secondary)' }}>
                <span>缩放</span>
                <span>{display.scale.toFixed(2)}×</span>
              </div>
              <input
                type="range"
                min={FRAMING_SCALE_MIN}
                max={FRAMING_SCALE_MAX}
                step={FRAMING_SCALE_STEP}
                value={display.scale}
                disabled={loading}
                onChange={(e) => updateField({ scale: parseFloat(e.target.value) })}
                className="w-full"
              />
            </div>

            {/* offsetX */}
            <div>
              <div className="text-[10px] mb-1"
                   style={{ color: 'var(--color-text-secondary)' }}>
                X 偏移(px · 正数右移)
              </div>
              <input
                type="number"
                min={FRAMING_OFFSET_MIN}
                max={FRAMING_OFFSET_MAX}
                step={1}
                value={xText}
                disabled={loading}
                onFocus={() => { xEditingRef.current = true; }}
                onBlur={() => {
                  xEditingRef.current = false;
                  setXText(String(Math.round(display.offsetX)));
                }}
                onChange={(e) => {
                  const v = e.target.value;
                  setXText(v);
                  // 空串 / "-" / 非法 → 当 0 但不强制改 text(允许中途态)
                  const parsed = parseFloat(v);
                  const num = Number.isFinite(parsed) ? parsed : 0;
                  updateField({ offsetX: num });
                }}
                className="w-full rounded px-2 py-1 text-xs"
                style={{
                  background: 'var(--color-bg-input)',
                  color: 'var(--color-text-primary)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </div>

            {/* offsetY */}
            <div>
              <div className="text-[10px] mb-1"
                   style={{ color: 'var(--color-text-secondary)' }}>
                Y 偏移(px · 正数下移 → 脚出框 = 半身锚底)
              </div>
              <input
                type="number"
                min={FRAMING_OFFSET_MIN}
                max={FRAMING_OFFSET_MAX}
                step={1}
                value={yText}
                disabled={loading}
                onFocus={() => { yEditingRef.current = true; }}
                onBlur={() => {
                  yEditingRef.current = false;
                  setYText(String(Math.round(display.offsetY)));
                }}
                onChange={(e) => {
                  const v = e.target.value;
                  setYText(v);
                  const parsed = parseFloat(v);
                  const num = Number.isFinite(parsed) ? parsed : 0;
                  updateField({ offsetY: num });
                }}
                className="w-full rounded px-2 py-1 text-xs"
                style={{
                  background: 'var(--color-bg-input)',
                  color: 'var(--color-text-primary)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </div>
          </div>

          {/* 按钮 */}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onReset}
              disabled={loading || saving}
              className="text-[10px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-bg-input)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
              title="复位到 1.0× / offset 0"
            >
              <RotateCcw size={10} />
              重置
            </button>
            <button
              type="button"
              onClick={() => void onSave()}
              disabled={!dirty || loading || saving}
              className="text-[10px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-bubble-ai-text)',
              }}
            >
              <Save size={10} className={saving ? 'animate-pulse' : ''} />
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

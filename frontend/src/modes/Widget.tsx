import { useRef, useState } from 'react';
import { useAppStore } from '../store';
import { applyModeWindowProps } from '../lib/window';
import CharacterView from '../components/CharacterView';
import StatusBadge from '../components/StatusBadge';
import AsrPreview from '../components/AsrPreview';
import VadBar from '../components/VadBar';
import ControlBar from '../components/ControlBar';
import WidgetTextInput from '../components/WidgetTextInput';

export default function Widget() {
  const status       = useAppStore((s) => s.status);
  const asrText      = useAppStore((s) => s.asrText);
  const asrTimestamp = useAppStore((s) => s.asrTimestamp);
  const setMode      = useAppStore((s) => s.setMode);
  // 2026-06-05 · ControlBar Keyboard 按钮翻 inputMode='text'/'voice' · 之前
  // 无消费者 · 这里订阅 · text 态在 ControlBar 上方渲染 WidgetTextInput 浮件。
  const inputMode    = useAppStore((s) => s.inputMode);

  const handleOpenPanel = async () => {
    await applyModeWindowProps('panel');
    setMode('panel');
  };

  const [controlsVisible, setControlsVisible] = useState(true);
  const leaveTimerRef = useRef<number | null>(null);

  const handleMouseEnter = () => {
    if (leaveTimerRef.current !== null) {
      clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
    setControlsVisible(true);
  };

  const handleMouseLeave = () => {
    leaveTimerRef.current = window.setTimeout(() => {
      setControlsVisible(false);
      leaveTimerRef.current = null;
    }, 200);
  };

  const controlsClass = `transition-opacity duration-200 ${controlsVisible ? 'opacity-100' : 'opacity-0'}`;

  return (
    // bugfix-4 (4.3): widget 外层加 data-tauri-drag-region → 整个空白区域 (包括
    // Live2D 渲染区) 都能拖窗。子元素带 onClick 的 <button> 不受影响 (Tauri 2
    // 检查 event.target 是否带 data-tauri-drag-region, 子元素不继承)。
    // App.tsx 顶 h-6 strip 仍保留作显式 hint, 但不再是唯一拖动区。
    <div
      data-tauri-drag-region
      className="w-full h-full relative"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Character — z-0, fills entire window. data-tauri-drag-region=false 让
          点击 Live2D 不被解释成 click-event (touch 系统仍 work, 因为 CharacterView
          内部用 mousedown / pointerdown 不 click)。Actually 让它保持可拖即可,
          不显式设 false。 */}
      <CharacterView />

      {/* Status badge — top-left, hover-controlled */}
      <div className={`absolute top-3 left-3 z-20 ${controlsClass}`}>
        <StatusBadge status={status} />
      </div>

      {/* 2026-06-06 · 删 WidgetSpeechBubble · 小窗只用 AsrPreview(实时 ASR
          回显) + Live2D 嘴动 + TTS 出声,不再叠成句台词气泡浮件。 */}

      {/* ASR preview — centered above control bar */}
      <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-20">
        <AsrPreview text={asrText} timestamp={asrTimestamp} />
      </div>

      {/* VAD bar — reads recording/vadState from store directly。bugfix-4 (4.3):
          idle 不渲染 (VadBar.tsx 内部判断), 不再出现"屏幕中间一道线"幻觉。 */}
      <div className="absolute bottom-16 left-3 right-3 z-10 pointer-events-none">
        <VadBar />
      </div>

      {/* 2026-06-05 · Widget text input — 仅 inputMode==='text' 时渲染 ·
          位于 ControlBar(bottom:12 + 36 高 = 顶 48)之上 8px 间距 = bottom:56 ·
          跟 VadBar(bottom:64)有 8px overlap 但 VadBar idle 不渲染(text 态
          vadState=sleep 自然不渲染)· hover 控制跟其它浮件同节奏。 */}
      {inputMode === 'text' && (
        <div
          data-tauri-drag-region="false"
          className={`absolute z-20 isolate ${controlsClass}`}
          style={{ bottom: '56px', left: '12px', right: '12px' }}
        >
          <WidgetTextInput />
        </div>
      )}

      {/* Control bar — hover-controlled. bugfix-4 (4.3): JSX ``={false}`` 会让
          属性消失,改成显式字符串 "false" (Tauri 检查 attribute presence) +
          ``relative isolate`` 提升层叠上下文确保 buttons 可点击。 */}
      <div
        data-tauri-drag-region="false"
        className={`absolute bottom-3 left-3 right-3 z-20 isolate ${controlsClass}`}
      >
        <ControlBar onSettings={handleOpenPanel} />
      </div>
    </div>
  );
}

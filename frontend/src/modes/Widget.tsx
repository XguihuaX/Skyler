import { useRef, useState } from 'react';
import { useAppStore } from '../store';
import { applyModeWindowProps } from '../lib/window';
import CharacterView from '../components/CharacterView';
import StatusBadge from '../components/StatusBadge';
import AsrPreview from '../components/AsrPreview';
import VadBar from '../components/VadBar';
import ControlBar from '../components/ControlBar';

export default function Widget() {
  const status       = useAppStore((s) => s.status);
  const asrText      = useAppStore((s) => s.asrText);
  const asrTimestamp = useAppStore((s) => s.asrTimestamp);
  const setMode      = useAppStore((s) => s.setMode);

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
    <div
      className="w-full h-full relative"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Character — z-0, fills entire window */}
      <CharacterView />

      {/* Status badge — top-left, hover-controlled */}
      <div className={`absolute top-3 left-3 z-20 ${controlsClass}`}>
        <StatusBadge status={status} />
      </div>

      {/* ASR preview — centered above control bar */}
      <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-20">
        <AsrPreview text={asrText} timestamp={asrTimestamp} />
      </div>

      {/* VAD bar — reads recording/vadState from store directly */}
      <div className="absolute bottom-16 left-3 right-3 z-10">
        <VadBar />
      </div>

      {/* Control bar — hover-controlled */}
      <div className={`absolute bottom-3 left-3 right-3 z-20 ${controlsClass}`}>
        <ControlBar onSettings={handleOpenPanel} />
      </div>
    </div>
  );
}

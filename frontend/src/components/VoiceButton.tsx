import React from 'react'

interface VoiceButtonProps {
  onRecordStart: () => void
  onRecordStop: (audioBlob: Blob) => void
  isRecording: boolean
}

const VoiceButton: React.FC<VoiceButtonProps> = ({
  onRecordStart,
  onRecordStop,
  isRecording,
}) => {
  return (
    <button className={`voice-btn${isRecording ? ' voice-btn--recording' : ''}`}>
      {/* 语音录制按钮 */}
    </button>
  )
}

export default VoiceButton

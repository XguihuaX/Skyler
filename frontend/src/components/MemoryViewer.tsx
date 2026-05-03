import React from 'react'

interface Memory {
  id: number
  type: string
  content: string
  created_at: string
}

interface MemoryViewerProps {
  userId: string
}

const MemoryViewer: React.FC<MemoryViewerProps> = ({ userId }) => {
  const [memories, setMemories] = React.useState<Memory[]>([])

  return (
    <div className="memory-viewer">
      {/* 记忆面板展示与编辑 */}
    </div>
  )
}

export default MemoryViewer

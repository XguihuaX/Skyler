import React from 'react'

interface Character {
  id: string
  name: string
  avatar: string
}

interface CharacterSelectProps {
  onSelect: (character: Character) => void
  currentCharacter: Character | null
}

const CharacterSelect: React.FC<CharacterSelectProps> = ({
  onSelect,
  currentCharacter,
}) => {
  return (
    <div className="character-select">
      {/* 角色选择组件 */}
    </div>
  )
}

export default CharacterSelect

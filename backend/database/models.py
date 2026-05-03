from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    user_name = Column(String, nullable=False)
    profile_summary = Column(Text, nullable=True)   # free-text profile, merged by LLM
    nickname = Column(Text, nullable=True)
    language = Column(Text, nullable=True, default="zh-CN")
    created_at = Column(DateTime, server_default=func.now())

    memories = relationship("Memory", back_populates="user")
    todos = relationship("Todo", back_populates="user")
    chat_history = relationship("ChatHistory", back_populates="user")
    conversations = relationship("Conversation", back_populates="user")


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    persona = Column(Text, nullable=False)
    avatar_path = Column(Text, nullable=True)
    # v3-B: 角色专属 TTS 音色标识，留空表示沿用全局默认（仅存不用，等 SoVITS 接入）
    voice_model = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    conversations = relationship("Conversation", back_populates="character")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    title = Column(String, nullable=False, default="新对话")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="conversations")
    character = relationship("Character", back_populates="conversations")


class Memory(Base):
    __tablename__ = "memory"
    __table_args__ = (
        CheckConstraint("role IN ('user','system')", name="ck_memory_role"),
        CheckConstraint(
            "type IN ('fact','instruction','emotion','activity','daily')",
            name="ck_memory_type",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    role = Column(String, nullable=False)
    type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(LargeBinary, nullable=True)
    expires_at = Column(DateTime, nullable=True)    # NULL = permanent; set for transient states
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="memories")


class Todo(Base):
    __tablename__ = "todos"
    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('alarm','agent','schedule')", name="ck_todo_owner_type"
        ),
        CheckConstraint(
            "status IN ('pending','completed','failed','multiple')",
            name="ck_todo_status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    owner_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    due_time = Column(DateTime, nullable=False)
    status = Column(String, default="pending")
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="todos")


class ChatHistory(Base):
    __tablename__ = "chat_history"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_chat_role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="chat_history")

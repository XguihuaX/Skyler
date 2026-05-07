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
    # v3-E1: Live2D 模型标识，对应 frontend/public/live2d/<name>/ 目录名。
    # NULL = 不启用 Live2D，回退到 avatar_path 静态图片。
    live2d_model = Column(Text, nullable=True)
    # v3-E2: per-character emotion / motion / hit-area map JSON 字段。
    # 全部 TEXT NULL，前端 resolveCharacterMaps 在 NULL / 空 / parse 失败时
    # 回退到 v3-E1 的全局默认（config/live2d.ts emotionMap / motionMap）。
    # 详见 migrations/v3_e2_per_character_maps.py 字段语义。
    emotion_map_json  = Column(Text, nullable=True)
    motion_map_json   = Column(Text, nullable=True)
    hit_area_map_json = Column(Text, nullable=True)
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
    # v3-F：被语音 / UI 打断截断时记录时间戳。None = 正常完成。仅 assistant 行使用。
    interrupted_at = Column(DateTime, nullable=True)
    # v3-E1 Step Z.2：这一行是怎么产生的，决定下游 profile_summary 等是否纳入。
    # 'normal' / 'touch' / 'proactive' —— application 层校验，不下放到 DB enum。
    # touch / assistant 一对都标 'touch'；详见 migrations/v3_e1_z.py 注释。
    kind = Column(
        String(16),
        nullable=False,
        default="normal",
        server_default="normal",
    )
    # v3-G chunk 2：当 kind='proactive' 时记录是哪个 trigger 拉起的
    # （如 'morning_briefing'）；其他 kind 该列 NULL。详见
    # migrations/v3_g_chunk2_proactive.py。
    proactive_trigger = Column(String(64), nullable=True)

    user = relationship("User", back_populates="chat_history")


class PendingBriefing(Base):
    """v3-G chunk 2.6 — wake_call_briefing 跨进程中间状态。

    stage 1（cron）写一行带聚合数据；stage 2（用户响应）ChatAgent
    `_build_messages` 读出最近未消费 + 未过期的行，注入 addendum 后标
    consumed_at。详见 migrations/v3_g_chunk2_6_pending_briefing.py 字段
    语义。
    """
    __tablename__ = "pending_briefings"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    user_id            = Column(String(64), nullable=False)
    trigger_name       = Column(String(64), nullable=False)
    briefing_data_json = Column(Text, nullable=False)
    character_id       = Column(Integer, nullable=False)
    conversation_id    = Column(Integer, nullable=False)
    created_at         = Column(DateTime, nullable=False, server_default=func.now())
    ttl_minutes        = Column(Integer, nullable=False, default=30, server_default="30")
    consumed_at        = Column(DateTime, nullable=True)

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    user_name = Column(String, nullable=False)
    # [RETIRED 2026-05-19] profile_summary 字段已退役 — chunk 11 profile_data
    # 接管"用户画像";chat.py fallback / users_api 端点 / service 函数全清。
    # 列保留空列以避免不可逆 DROP COLUMN(SQLite 上破坏性);无活读写。后续
    # 单独小刀可 DROP COLUMN。
    profile_summary = Column(Text, nullable=True)
    # v3.5 chunk 11：结构化 profile（JSON 字符串），schema 见
    # backend/utils/profile_schema.py PROFILE_SCHEMA_V1。注入 system prompt
    # 的唯一源(2026-05-19 起,不再 fallback 到 profile_summary)。
    profile_data = Column(Text, nullable=True)
    nickname = Column(Text, nullable=True)
    language = Column(Text, nullable=True, default="zh-CN")
    # V4 持久化"上次选的角色" · 软引用 characters.id · 不设 FK 约束(SQLite FK
    # 默认不强制 · 且需求"指向已删角色 → 静默回落 Momo 别崩"应用层校验更直接)。
    # 写入点:ws.py character_switch handler;读取点:ws.py _resolve_conv_char +
    # users_api GET /profile + 前端 App.tsx mount(后两者一起喂前端启动角色决策)。
    current_character_id = Column(Integer, nullable=True)
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
    # v3.5 chunk 5a: per-character 背景层 Vite static URL（如
    # ``/backgrounds/tokyo_rain.mp4``）。NULL → CharacterView 继续走原
    # fallback 链（Live2D → 静态 jpeg）。后缀决定前端用 <img> 还是 <video>。
    background_path = Column(Text, nullable=True)
    # v4-fan chunk 1: Fan UI 扇面卡牌底图。Vite static URL（如
    # ``/splash-art/2.jpg``）。NULL → Fan UI fallback 占位。文件名以
    # character.id 为 key，由 POST /api/characters/{id}/splash-art 写入。
    splash_art_url = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    conversations = relationship("Conversation", back_populates="character")
    personas = relationship("CharacterPersona", back_populates="character",
                            cascade="all, delete-orphan")


class Live2DModelSettings(Base):
    """2026-06-16 INV · per-Live2D-model 设置容器。

    挂模型(model_key = scanner slug · 等于 frontend/public/live2d/<slug>/
    目录名 · 也等于 character.live2d_model)· 不挂 character.id —— 模型原生
    比例决定怎么裁,共用 slug 的角色共享 framing。

    settings_json 容器形(本期只写 framing 一个 section · 其它键透传不动):
        {
          "framing": { "scale": 1.0, "offsetX": 0, "offsetY": 0 }
          // 留位:param_map / director / future
        }
    """
    __tablename__ = "live2d_model_settings"

    model_key     = Column(Text, primary_key=True)
    settings_json = Column(Text, nullable=False)
    updated_at    = Column(DateTime, server_default=func.now())


class CharacterPersona(Base):
    """v4 persona engineering segment 1 — multi-variant persona schema.

    一个 character 可有多个 persona variant（``default`` / ``user_custom_1`` / 等）；
    partial UNIQUE INDEX ``idx_persona_active_per_char`` (见
    migrations/v4_persona_thickening_segment1.py) 保证同 character 任意时刻只有
    一行 ``is_active=1``。

    7 个 Tier-1 字段以 JSON-in-TEXT 存（SQLite 无 JSON 类型）：renderer 侧的
    ``persona_loader`` 负责 ``json.loads`` 解析；写入前 caller 负责 ``json.dumps``。
    """
    __tablename__ = "character_personas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_name = Column(Text, nullable=False)
    is_builtin = Column(Boolean, default=False, server_default="0")
    is_active = Column(Boolean, default=False, server_default="0")
    display_order = Column(Integer, default=0, server_default="0")
    description = Column(Text, nullable=True)

    # Tier-1 必填（JSON-in-TEXT）
    identity = Column(Text, nullable=False)
    personality_core = Column(Text, nullable=False)
    speech_style = Column(Text, nullable=False)
    signature_phrases = Column(Text, nullable=False)
    voice_samples = Column(Text, nullable=False)
    forbidden_phrases = Column(Text, nullable=False)
    relationship_to_user = Column(Text, nullable=False)

    # Tier-2 可选（NULL 表示走默认）
    taboo_topics = Column(Text, nullable=True)
    lore = Column(Text, nullable=True)
    capability_overrides = Column(Text, nullable=True)
    style_preset = Column(Text, default="anime_classic",
                          server_default="anime_classic")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    character = relationship("Character", back_populates="personas")

    __table_args__ = (
        UniqueConstraint("character_id", "variant_name",
                         name="uq_character_personas_char_variant"),
    )


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
    # v3.5 chunk 9 Part 4：forgetting curve 元数据
    access_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_accessed_at = Column(DateTime, nullable=True)  # NULL → 视同 created_at
    # v3.5 chunk 10：server-side extractor + 显式 save_memory tool 元数据
    extracted_at = Column(DateTime, nullable=True)
    source_turn_id = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
    # entry_type 与 type 区别：``type`` 是 chunk 2 五分类约束（fact/instruction/
    # emotion/activity/daily）；``entry_type`` 是 chunk 10 worker 抽出的四分类
    # （fact/preference/event/commitment），二者并存允许 UI 双维度展示。
    entry_type = Column(Text, nullable=True)
    extraction_source = Column(
        Text, nullable=False, default="legacy", server_default="legacy",
    )

    user = relationship("User", back_populates="memories")


# [RETIRED 2026-05-19] todos 链路全退役 — LLM 工具(add_todo / delete_todo /
# search_todo)、AlarmScheduler、/api/todos/* 路由、services todo 函数全删。
# 提醒改由 ``apple_calendar.create_event``(macOS EventKit)。保留空表 + ORM
# class 避免不可逆 DROP TABLE;无活代码消费。后续可单独小刀 DROP。
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


class CharacterState(Base):
    """v3-G chunk 3b — 角色跨 turn 状态。

    与 ``ChatHistory.kind`` / 单轮 ``emotion`` 标签的语义关系：

      * ``emotion`` (chunk D)        ─ per-turn 瞬时（"这一句开心"），不持久
      * ``CharacterState.mood``      ─ 跨 turn 累积情绪（"今天整体心情"），持久

    两套独立不冲突：emotion 控 TTS / Live2D 当轮表现；mood 控状态条 + 后续
    系统的"角色感"——比如 mood='tired' 时人设倾向偏低能量。

    UNIQUE(character_id) 强制一对一。一个 character 只有一行 state；查询
    用 character_id 直接 lookup。
    """
    __tablename__ = "character_states"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    character_id        = Column(Integer, nullable=False, unique=True)
    mood                = Column(String(32), nullable=False, default="neutral",
                                 server_default="neutral")
    intimacy            = Column(Integer, nullable=False, default=0,
                                 server_default="0")
    current_thought     = Column(Text, nullable=True)
    current_activity    = Column(String(64), nullable=True)
    last_interaction_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at          = Column(DateTime, nullable=False, server_default=func.now())


class CharacterDailyPlan(Base):
    """DailyAgent Stage 1 — per-character per-day 活动日程。

    一行 = 一个 character 在某一本地日期(scheduler timezone)的全天 plan。
    plan 是 JSON 字符串(SQLite 无原生 JSON 类型),形如:

        [{"start": "07:00", "end": "08:30", "activity": "起床 + 早饭"}, ...]

    UNIQUE(character_id, date) 防同日重复;ticker 每 5min 查今日 row、按当前
    本地 HH:MM 命中 slot → 写 ``character_states.current_activity``。
    """
    __tablename__ = "character_daily_plans"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    character_id = Column(Integer, nullable=False)
    date         = Column(Date, nullable=False)
    plan         = Column(Text, nullable=False)
    created_at   = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "character_id", "date",
            name="uq_character_daily_plans_char_date",
        ),
    )


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

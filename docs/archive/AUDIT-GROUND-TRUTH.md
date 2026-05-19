# AUDIT-GROUND-TRUTH

> **本轮性质**：用户离线 ~4h，无人中继。仅产出只读审计报告。
> 不 commit / 不 push / 不改代码 / 不改 schema / 不动 stash / 不删任何东西。
> 报告中最强措辞 = "零活消费者·疑似死(待人工核，本轮不处理)"。
> 工作目录：`/Users/liujunhong/Desktop/MomoOS-v2`
> 审计日期：2026-05-18（current date 系统注入）
> 编写者：Claude Code（Opus 4.7，只读权限）
>
> ---

## 第0节 零动作 / 基线核真

### 0.1 `git log --oneline 5e55721..HEAD`（HEAD 链）

```
2d7b793 docs(memory): v4.0.0 记忆线收口纠真——audit完+修复链已ship(代码核验)/功能待真机回归;§5.8表层债入册;DESIGN.md大整合立项;不碰代码/Z.5/历史段/stash    ← HEAD
3f3be08 feat(memory): 墓碑表——删过的"持久事实"不再被重抽(仅 expires_at IS NULL;双删入口写墓碑+双去重比对;精确/cosine≥0.92;不碰supersede/expires_at/召回)
bfcd821 feat(memory): 抽取 prompt 重平衡——随口单次的稳定锚也抽,recurrence 降为只提confidence;护栏(不提取/反推词/schema/第三人称)不动
42d1800 fix(memory): delete_conversation 源头幂等 reconcile 指针(按user剩余MAX,clamp-only不前进;配合Patch B纵深)
f712625 fix(memory): extractor 指针越界自愈 clamp 到 user MAX(id)(解开 default 卡死804;不动删除路径/抽取策略)
1437e48 fix(memory): restore log 文本对齐真实 limit(打印 SHORT_TERM_MAX 真值,消除 stale "limit=20")
902c2c2 fix(memory): 重启恢复窗口对齐 SHORT_TERM_MAX(闭合 caveat2 单conv重启冷启动gap;不动 fold/注入/指针/caveat1)
b91505a feat(memory): 加有界滚动摘要层(新表+独立触发工人+重压缩非append+Qwen3.5-Flash可配+注入),不动指针/抽取策略
```

8 条 commit（不含 5e55721 起点），与 DESIGN.md §Z.5.1 表格逐行对得上。

### 0.2 `git log --oneline origin/main..HEAD`（未 push 检测）

输出为空 → **HEAD 已与 origin/main 同步，零未 push commit**。
（注：远端 HEAD 为 `origin/main`，仓库无 `origin/HEAD` symbolic-ref，因此直接以 `origin/main` 对账。）

### 0.3 `git status --porcelain`

```
?? DESIGN_patch.md
?? frontend/public/splash-art/100.png
?? frontend/public/splash-art/101.png
?? frontend/public/splash-art/2.png
?? frontend/public/splash-art/3.png
?? frontend/public/splash-art/99.png
?? momoos.db.backup_2bugfix_20260516_1704
?? momoos.db.backup_bindfix_20260516_1340
?? momoos.db.backup_chatpanel_20260516_1555
?? momoos.db.backup_diag_20260517_000427
?? momoos.db.backup_memsum_20260517_015154
?? momoos.db.backup_purge_20260516_1245
?? momoos.db.backup_zh_revert_20260516_1038
?? momoos.db.before-mai-injection
?? voice_clone_local.py
```

全部为 untracked，**无 staged / modified**。已被 `.gitignore` 或人为留作本地副本（DB 备份系列 7 个、立绘 PNG 5 张、`voice_clone_local.py`、`DESIGN_patch.md`）。
本轮**不做任何 add / clean / rm**。

### 0.4 `git stash list`

```
stash@{0}: On main: park: 个人config+调试桩(memsum刀前)
```

stash@{0} 在册，**本轮不动**（不 pop / 不 drop / 不 show）。

### 0.5 14 个 sentinel forbidden commit 的判定

DESIGN.md L4687 原文：
> 修复链(均叠于 5e55721 之上;全程 14 sentinel commit 未动,stash 未动)

文档明确"14 sentinel commit"是修复链作业期间被锁定不动的旧基线。在仓库内**只有此一处出现"14 sentinel commit"字面**（grep 已确认）。文档未列出具体 14 个 sha → 本轮基于以下两种候选解释列出 sha 集合，并标 ⚠️ 待人工裁决究竟取哪一种解释。

**候选 A（5e55721 自身为锚 + 之下 13 条 = 14）**：

| # | sha | subject |
|---|---|---|
| 1 | 5e55721 | docs: Task A 收口（DESIGN_patch 6-Patch + README×2/ROADMAP/DESIGN_LITE 整文件替换），零代码改动 |
| 2 | 5766493 | fix(ws): character_switch 不杀 in-flight turn — 兑现 Rule A 不丢 |
| 3 | eeb427a | fix(memory): short_term per-conversation 过滤 — 修删对话+重启仍串旧上下文 |
| 4 | f79495c | fix(ui): 历史迁入左侧聊天栏 + 切角色自动加载最新对话(对齐 conversation 锚定) |
| 5 | 9039d75 | fix(binding): conversation-anchored character/chat_id — 对话发起锁定 + proactive 投递校验 |
| 6 | cfa006c | fix(data): purge cid≠1 polluted chat_history |
| 7 | 0c9c082 | fix(ws): correct character_id in _update_memory (b5b0a47 收尾) |
| 8 | 9e434e3 | fix(data): purge cid=1 polluted chat_history (ja/verbose precedent) |
| 9 | b5b0a47 | fix(memory): short_term per-(user,character) + restore character/tag filter |
| 10 | 0e079a4 | feat(tts): Mai 回退纯中文 — tts_language=zh + 换中文 voice,ja 链挂起留 v4.1 |
| 11 | f6a0f99 | fix(ai_providers): persist custom vendor models across backend restart |
| 12 | c106f91 | fix(tts): final guard against literal <ja>/<en> tags reaching TTS provider |
| 13 | 1c094bd | fix(text_filters): exempt <ja>/<en> from SUSPICIOUS_TAG_RE strip |
| 14 | 63d0af2 | docs(persona): Mai persona JSON spec — v4-beta Tier-1+Tier-2 reference |

**候选 B（5e55721 之下整 14 条 = 不含 5e55721 本身）**：

候选 A 的 #2–#14 + `dbc851a perf(chat): truncate tool_result to 4000 chars — prevent multi-round tool input bloat`

依据：DESIGN.md §Z.6 token 治理把 `dbc851a` 与 `59249f8` 都列入"Z.2 三级隔离同 commit 系列"——若把"上一线索基线"也算 sentinel，dbc851a 是天然候选；但 §Z.5.1 上下文措辞偏向"以 5e55721 为锚向上叠 fix"，从语义上 5e55721 本身被视为 sentinel 的概率更高。

⚠️ **待人工裁决**：14 sentinel commit 具体 sha 集合（采用候选 A 还是 B 还是其它），本轮无证据二选一。本轮无论如何 **不会 rebase / amend / revert / cherry-pick** 任一 commit。

### 0.6 基线结论

| 项 | 状态 |
|---|---|
| HEAD | `2d7b793`（最新 docs 纠真 commit，符合 DESIGN.md §Z.5.1 描述） |
| 与 origin/main 同步 | ✅ 0 未 push commit |
| 工作区 | 仅 15 个 untracked（DB 备份 / 立绘 PNG / 个人脚本 / DESIGN_patch.md），无 staged / modified |
| stash@{0} | 在册，未动 |
| 14 sentinel sha 具体清单 | ⚠️ 待人工裁决（候选 A/B 见 0.5） |

**无异常**——除 sentinel sha 集合需人工确认外，其余基线全部健康。本轮可安全推进后续只读节。

---

## 第1节 真 schema（只读，逐表 + 写入源）

### 1.0 表清单 + 一处关键 ⚠️

`.tables` 实出 22 张：activity_sessions, ai_providers, ai_vendor_credentials, ai_vendors, character_personas, character_personas_builtin_seed, character_states, characters, chat_history, conversation_summary, conversations, mcp_client_state, mcp_credentials, mcp_tool_state, memory, memory_extractor_state, pending_briefings, sqlite_sequence, todos, tts_call_log, users, voice_aliases。

⚠️ **关键发现**：commit `3f3be08` 引入的 `memory_tombstone` 表在 migration 代码（`backend/database/migrations/v4_0_0_memory_tombstone.py`）里有，但 **momoos.db 实际不存在**——backend 启动会跑 migration（`backend/main.py:388`），现有 DB 文件 mtime=2026-05-17 02:24，说明真机一次都还未在最新 commit 链上启动过；`services.delete_memory:186` 的 `INSERT INTO memory_tombstone` 若在 backend 未跑过 migration 的环境直接调用会抛 OperationalError。⚠️ 待真机回归确认 migration 正确执行。

### 1.1 行数实测

| 表 | 行数 | 备注 |
|---|---|---|
| users | 19 | 1 真 (default) + 18 测试残留 |
| memory | 9 | **default 用户 0 行**；9 行全是测试 uid |
| chat_history | 8 | 全部 user=default & character_id=1 |
| todos | 1 | |
| characters | 8 | |
| conversations | 23 | |
| pending_briefings | 234 | **default 0 行**；全测试残留 |
| character_states | 20 | vs 8 characters → 部分测试 character_id |
| mcp_credentials | 0 | 待配置型 |
| mcp_client_state | 6 | |
| mcp_tool_state | 0 | 待启用型 |
| memory_extractor_state | 3 | |
| activity_sessions | 868 | 真采集 |
| ai_vendors | 4 | |
| ai_vendor_credentials | 1 | |
| ai_providers | 6 | |
| voice_aliases | 4 | |
| tts_call_log | 510 | |
| character_personas | 8 | |
| character_personas_builtin_seed | 8 | |
| conversation_summary | 1 | v4.0.0 b91505a 新引入 |
| memory_tombstone | **(表不存在)** | 见 1.0 |

### 1.2 users — 真 schema + 写入源

```sql
CREATE TABLE users (
    user_id VARCHAR NOT NULL,
    user_name VARCHAR NOT NULL,
    profile_summary TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    nickname TEXT,
    language TEXT DEFAULT 'zh-CN',
    profile_data TEXT,
    PRIMARY KEY (user_id)
);
```

写入：`backend/database/services.py:37` (`create_user`)。
profile_summary 更新：`backend/database/services.py:60` (`update_profile_summary`)。
单一真用户：`default / Momo / Skyler / zh-CN`；其余 18 行为前缀 `test_* / pb_user* / wc_* / mem_user / agg_user` 的测试残留。

### 1.3 memory — 真 schema + 写入源

```sql
CREATE TABLE memory (
    id INTEGER NOT NULL,
    user_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,
    expires_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    character_id INTEGER,
    access_count INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMP,
    extracted_at TIMESTAMP,
    source_turn_id INTEGER,
    confidence REAL,
    quality_score REAL,
    entry_type TEXT,
    extraction_source TEXT NOT NULL DEFAULT 'legacy',
    PRIMARY KEY (id),
    CONSTRAINT ck_memory_role CHECK (role IN ('user','system')),
    CONSTRAINT ck_memory_type CHECK (type IN ('fact','instruction','emotion','activity','daily')),
    FOREIGN KEY(user_id) REFERENCES users (user_id)
);
```

写入：
- `backend/database/services.py:111` (`add_memory` ORM)
- `backend/memory/extractor.py:247` (`INSERT INTO memory` raw — server-side 抽取链路)
- `backend/agents/chat.py:851` (`session.add(Memory(...))` — ChatAgent ORM)
- `backend/agents/chat.py:688` (`INSERT INTO memory` raw — ChatAgent 另一路径)

实测：default 用户 **0 memory 行**，9 行全是测试 uid (mem_user / test_proactive / test_pt2 各 3)。与 DESIGN.md §Z.5 audit 一致；§Z.5.1 修复链已 ship 但 momoos.db mtime 在最后 fix commit 前 → ⚠️ 真机回归未跑，无法验证修复是否使 default 用户产生新 memory。

### 1.4 todos — 真 schema + 写入源

```sql
CREATE TABLE todos (
    id INTEGER NOT NULL,
    user_id VARCHAR NOT NULL,
    owner_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT,
    due_time DATETIME NOT NULL,
    status VARCHAR,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT ck_todo_owner_type CHECK (owner_type IN ('alarm','agent','schedule')),
    CONSTRAINT ck_todo_status CHECK (status IN ('pending','completed','failed','multiple')),
    FOREIGN KEY(user_id) REFERENCES users (user_id)
);
```

写入：`backend/database/services.py:232` (`create_todo`)。
更新：`backend/database/services.py:287` (`update_todo_status`)。
删除：`backend/database/services.py:358` (`delete_todo`)。

### 1.5 chat_history — 真 schema + 写入源

```sql
CREATE TABLE chat_history (
    id INTEGER NOT NULL,
    user_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    conversation_id INTEGER,
    character_id INTEGER,
    interrupted_at DATETIME,
    kind TEXT NOT NULL DEFAULT 'normal',
    proactive_trigger TEXT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_chat_role CHECK (role IN ('user','assistant')),
    FOREIGN KEY(user_id) REFERENCES users (user_id)
);
```

写入：`backend/database/services.py:469` (`add_chat_history` ORM，唯一入口)。
删除路径：`services.delete_conversation` → 在 commit `42d1800` 后会同事务 `UPDATE memory_extractor_state` 把指针 clamp 回 user 剩余 MAX(id)。

### 1.6 characters — 真 schema + 写入源

```sql
CREATE TABLE characters (
    id INTEGER NOT NULL,
    name VARCHAR NOT NULL,
    persona TEXT NOT NULL,
    avatar_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    voice_model TEXT,
    live2d_model TEXT,
    emotion_map_json TEXT,
    motion_map_json TEXT,
    hit_area_map_json TEXT,
    background_path TEXT NULL,
    splash_art_url TEXT,
    PRIMARY KEY (id),
    UNIQUE (name)
);
```

写入：
- `backend/database/migrations/v2_5_b.py:78` (`INSERT INTO characters` — 首启 seed)
- `backend/routes/characters_api.py:151` (`session.add(c)` — UI CRUD)

8 行匹配 `characters.yaml` 8 个角色（详 §3）。

### 1.7 conversations — 真 schema + 写入源

```sql
CREATE TABLE conversations (
    id INTEGER NOT NULL,
    user_id VARCHAR NOT NULL,
    character_id INTEGER NOT NULL,
    title VARCHAR NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (user_id),
    FOREIGN KEY(character_id) REFERENCES characters (id)
);
```

写入：
- `backend/database/migrations/v2_5_b.py:102` (`INSERT INTO conversations` — backfill)
- `backend/proactive/engine.py:210` (`session.add(conv)` — 主动陪伴新建)
- `backend/routes/conversations_api.py:83` (`session.add(c)` — UI 新建)

### 1.8 pending_briefings — 真 schema + 写入源

```sql
CREATE TABLE pending_briefings (
    id INTEGER NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    trigger_name VARCHAR(64) NOT NULL,
    briefing_data_json TEXT NOT NULL,
    character_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ttl_minutes INTEGER DEFAULT '30' NOT NULL,
    consumed_at DATETIME,
    PRIMARY KEY (id)
);
CREATE INDEX idx_pending_briefings_lookup
    ON pending_briefings (user_id, consumed_at, created_at);
```

写入：`backend/database/services.py:551` (`add_pending_briefing`)。
234 行全部测试 uid，**真用户 default 0 行**。`services.py:578-595` 注释了 TTL housekeeping 但无自动清理 → ⚠️ 待人工核（本轮不动）。

### 1.9 character_states — 真 schema + 写入源

```sql
CREATE TABLE character_states (
    id INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    mood VARCHAR(32) DEFAULT 'neutral' NOT NULL,
    intimacy INTEGER DEFAULT '0' NOT NULL,
    current_thought TEXT,
    current_activity VARCHAR(64),
    last_interaction_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (character_id)
);
CREATE INDEX idx_character_state_char ON character_states (character_id);
```

写入：`backend/database/services.py:662` (`get_or_create_character_state`)。
更新：`backend/database/services.py:689` (`update_character_state`)。
20 行 vs 8 个 characters：unique(character_id) 显示有测试 character_id 残留 → ⚠️ 待人工核（本轮不动）。

### 1.10 mcp_credentials / mcp_client_state / mcp_tool_state — 真 schema + 写入源

```sql
CREATE TABLE mcp_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_name TEXT NOT NULL,
    key_name TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(server_name, key_name)
);
CREATE INDEX idx_mcp_creds_server ON mcp_credentials(server_name);

CREATE TABLE mcp_client_state (
    server_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE mcp_tool_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_name TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(server_name, tool_name)
);
CREATE INDEX idx_mcp_tool_state_server ON mcp_tool_state(server_name);
```

写入：
- `backend/mcp/credentials.py:73` (`INSERT INTO mcp_credentials`)
- `backend/mcp/credentials.py:109` (`INSERT INTO mcp_client_state`)
- `backend/mcp/tool_state.py:55` (`INSERT INTO mcp_tool_state`)

0 行（credentials / tool_state）= 待用户配置即写型，**非孤儿表**，活码就位。

### 1.11 memory_extractor_state — 真 schema + 写入源

```sql
CREATE TABLE memory_extractor_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    last_processed_turn_id INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

写入：`backend/memory/extractor.py:116` (`INSERT INTO memory_extractor_state`)。
更新：
- `backend/memory/extractor.py:122` (`UPDATE memory_extractor_state` — 抽取推进；f712625 clamp 越界自愈)
- `backend/routes/conversations_api.py:138` (`UPDATE memory_extractor_state` — delete_conversation reconcile，42d1800 源头幂等)

### 1.12 activity_sessions — 真 schema + 写入源

```sql
CREATE TABLE activity_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    start_at DATETIME NOT NULL,
    end_at DATETIME NOT NULL,
    duration_seconds INTEGER NOT NULL,
    app_name TEXT NOT NULL,
    browser_url TEXT,
    browser_title TEXT,
    category TEXT,
    is_idle_filtered INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_activity_sessions_user_date ON activity_sessions(user_id, start_at);
CREATE INDEX idx_activity_sessions_app ON activity_sessions(app_name);
```

写入：`backend/services/activity_timeline.py:247` (`INSERT INTO activity_sessions`)。
868 行真实采集。`user_id DEFAULT 'default'` —— 单用户退化语义但列活。

### 1.13 ai_vendors / ai_vendor_credentials / ai_providers — 真 schema + 写入源

```sql
CREATE TABLE ai_vendors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    vendor_kind TEXT NOT NULL DEFAULT 'custom'
        CHECK(vendor_kind IN ('builtin', 'custom')),
    default_endpoint TEXT,
    credential_key_name TEXT NOT NULL,
    color TEXT,
    icon TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    endpoint_env_name TEXT
);

CREATE TABLE ai_vendor_credentials (
    vendor_id TEXT PRIMARY KEY,
    key_value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES ai_vendors(id) ON DELETE CASCADE
);

CREATE TABLE ai_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id TEXT,
    type TEXT NOT NULL CHECK(type IN ('llm', 'asr', 'tts')),
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT,
    extra_json TEXT,
    provider_kind TEXT NOT NULL DEFAULT 'custom'
        CHECK(provider_kind IN ('builtin', 'custom')),
    enabled INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES ai_vendors(id) ON DELETE SET NULL
);
CREATE INDEX idx_ai_providers_type_active ON ai_providers(type, is_active);
CREATE INDEX idx_ai_providers_vendor ON ai_providers(vendor_id);
CREATE UNIQUE INDEX ix_ai_providers_vendor_name_type
    ON ai_providers(vendor_id, name, type);
```

写入：
- `backend/database/ai_providers.py:189` (`INSERT INTO ai_vendors`)
- `backend/database/ai_providers.py:277` (`INSERT INTO ai_vendor_credentials`)
- `backend/database/ai_providers.py:427` (`INSERT INTO ai_providers`)
- `backend/database/migrations/bugfix_3_1_ai_providers.py:208` (`INSERT INTO ai_providers` — builtin seed)

### 1.14 voice_aliases / tts_call_log — 真 schema + 写入源

```sql
CREATE TABLE voice_aliases (
    voice_id     TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tts_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL,
    character_id INTEGER,
    voice TEXT,
    model TEXT,
    input_chars INTEGER NOT NULL,
    input_preview TEXT,
    cost_estimate REAL,
    success INTEGER NOT NULL DEFAULT 1,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tts_log_timestamp ON tts_call_log(timestamp);
CREATE INDEX idx_tts_log_source ON tts_call_log(source);
```

写入：
- `backend/database/voice_aliases.py:45` (`INSERT INTO voice_aliases`)
- `backend/observability/tts_log.py:109` (`INSERT INTO tts_call_log`)

### 1.15 character_personas / character_personas_builtin_seed — 真 schema + 写入源

```sql
CREATE TABLE character_personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    variant_name TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 0,
    display_order INTEGER DEFAULT 0,
    description TEXT,
    identity TEXT NOT NULL,
    personality_core TEXT NOT NULL,
    speech_style TEXT NOT NULL,
    signature_phrases TEXT NOT NULL,
    voice_samples TEXT NOT NULL,
    forbidden_phrases TEXT NOT NULL,
    relationship_to_user TEXT NOT NULL,
    taboo_topics TEXT,
    lore TEXT,
    capability_overrides TEXT,
    style_preset TEXT DEFAULT 'anime_classic',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(character_id, variant_name)
);
CREATE UNIQUE INDEX idx_persona_active_per_char
    ON character_personas(character_id) WHERE is_active = 1;

CREATE TABLE character_personas_builtin_seed (
    character_id INTEGER NOT NULL,
    variant_name TEXT NOT NULL,
    seed_data TEXT NOT NULL,
    PRIMARY KEY(character_id, variant_name)
);
```

写入：
- `backend/database/migrations/v4_persona_thickening_segment1.py:171` (`INSERT INTO character_personas` — v4 seg1 seed)
- `backend/database/migrations/v4_persona_thickening_segment1.py:185` (`INSERT OR REPLACE INTO character_personas_builtin_seed`)
- `backend/database/migrations/v4_persona_segment2_ensure_defaults.py:90` (seg2 ensure defaults)
- `backend/routes/persona_api.py:264` (`session.add(p)` — UI CRUD)

builtin_seed 用途：`restore_to_builtin` 回滚源（DESIGN.md §F1）。

### 1.16 conversation_summary — 真 schema + 写入源

```sql
CREATE TABLE conversation_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    character_id INTEGER,
    conversation_id INTEGER,
    summary_text TEXT NOT NULL DEFAULT '',
    last_folded_chat_history_id INTEGER NOT NULL DEFAULT 0,
    token_budget INTEGER NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, character_id, conversation_id)
);
CREATE INDEX idx_conversation_summary_lookup
    ON conversation_summary(user_id, character_id, conversation_id);
```

写入：`backend/memory/summary.py:280` (`INSERT INTO conversation_summary`)。
更新：`backend/memory/summary.py:301` (`UPDATE conversation_summary`)。
1 行：commit `b91505a` 新引入有界滚动摘要层，已开始累积；活码非孤儿。

### 1.17 memory_tombstone（代码已就位，DB 表暂缺）

代码定义：`backend/database/migrations/v4_0_0_memory_tombstone.py:50`（`CREATE TABLE IF NOT EXISTS memory_tombstone`）+ `:61` 索引 `idx_memory_tombstone_user`。

写入路径（代码已就位）：`backend/database/services.py:186` (`INSERT INTO memory_tombstone`，在 `delete_memory` 同事务里，仅当 `expires_at IS NULL` 写入)。

召回侧消费：`backend/memory/tombstone.py` 提供 `is_tombstone_suppressed(content, user_id)` —— 精确 content / cosine≥0.92 双比对，被抽取链路调用（bfcd821 改造后）。

当前 momoos.db 文件**实测无此表**（`.tables` 不出现 memory_tombstone）→ migration 在 `backend/main.py:388` 注册，启动会跑。
⚠️ 待真机回归确认 migration 跑过 + delete_memory 写墓碑成功 + dup-check 真压制重抽。

### 1.18 sqlite_sequence

SQLite 系统表，存 AUTOINCREMENT 计数器；应用层无写入路径，跳过。

### 1.19 §1 写入源结论

- **无明显孤儿表**：22 张应用表全部有活跃写入源。
- 零行的表（`mcp_credentials / mcp_tool_state`）是"待用户配置即写"型，**非孤儿，活码就位**。
- 唯一"代码有 / DB 无"的表是 `memory_tombstone`，状态是 **migration pending**（非孤儿，是未启动一次）。
- 测试残留行（`memory / pending_briefings / character_states / users` 中的非 default 行）多张表里污染数据，处置方向="人工核要不要清"，**本轮不删任何行**。

---

## 第2节 列消费者 grep 审计（只读，全代码库）

按指令规则：
- 活/零活分级依据"消费者在 query WHERE / JOIN / scope key / schema 约束"出现
- 单用户退化（取值恒定）≠ 死列，结论写"活·单用户退化(NOT dead)"
- 最强措辞 = "零活消费者·疑似死(待人工核，本轮不处理)"，本节不写"可删"

### 2.1 `expires_at`（memory.expires_at）

**活·部分接线**

写入 path：
- `backend/database/services.py:108` (`add_memory` 接受参数)
- `backend/memory/long_term.py:272` (`add_memory_with_embedding` 接受)
- `backend/routes/memory_api.py:160` (UI POST 路径，`expires_at=body.expires_at`)
- `backend/routes/memory_api.py:207` (UI PATCH 路径，`m.expires_at = updates["expires_at"]`)
- `backend/agents/memory.py:127` (LLM tool `_handle_add_memory` 接受 `args["expires_at"]`)

读取 / 决策 path（**活的消费者**）：
- `backend/database/services.py:140` (`get_all_memories` `active_only` 过滤：`or_(Memory.expires_at.is_(None), Memory.expires_at > now)`)
- `backend/database/services.py:334` (`search_memory` 同 active_only 过滤)
- `backend/database/services.py:184` (`delete_memory` 仅当 `expires_at IS NULL` 写墓碑——commit 3f3be08 引入的硬门)
- `backend/agents/memory.py:72` (LLM tool 序列化返回)
- `backend/routes/memory_api.py:121/168/218` (UI 响应序列化)

**未传非 None 的写端**（"signature 接受但传 None"）：
- `backend/agents/chat.py:688` (ChatAgent raw INSERT，未带 expires_at 列)
- `backend/agents/chat.py:851` (ChatAgent ORM `session.add(Memory(...))`，未传 expires_at)
- `backend/memory/extractor.py:247` (server-side 抽取 raw INSERT，未带 expires_at)

DESIGN.md §Z.5.1 RT-4 原文"signature 接受但所有 caller 全传 None,写端从未利用"：**对 chat/extractor 主写入路径成立，但 LLM tool + UI 两条路径接受非 None**。
⚠️ 待人工核：真 DB 实测有无 `expires_at IS NOT NULL` 的 memory 行（本轮已知 default 用户 0 行，其他用户暂未实测，本节不动数据）。

### 2.2 `uid` vs `user_id` —— 同概念命名 vs 两个真实列

**结论：不是两个列。** `uid` 是局部变量名 / SQL 绑定参数名（如 `:uid`）的简写，遍布代码仅用作 `user_id` 的别名。`user_id` 才是所有相关表里的实列。

证据：
- 真 schema (`sqlite3 momoos.db ".schema" | grep -i uid`) **输出空** —— **没有任何表有 `uid` 列**。
- 真列 `user_id` 出现在：users PK / memory FK / todos FK / chat_history FK / conversations FK / pending_briefings / activity_sessions / memory_extractor_state / conversation_summary / memory_tombstone(migration)。
- `\buid\b` 字面共 63 处，全部是局部变量 / 函数参数 / SQL bind 名：
  - `backend/database/migrations/v2_5_b.py:94-133` `for (uid,) in users: ... :uid`
  - `backend/capabilities/activity.py:90/94/222/227/311/320` SQL bind `:uid` 对应 `user_id` 列
  - `backend/memory/extractor.py:342-372` 循环变量 `for uid in user_ids:`
  - `backend/services/profile_regen.py:412-422` 循环变量
  - `backend/routes/memory_api.py:46-47` 显式 helper `def _uid(user_id) -> str: return (user_id or "").strip() or _DEFAULT_UID`
  - `backend/routes/ws.py:102-104` docstring 中的简写
  - `backend/integrations/netease_music.py / bilibili.py` 是**完全不同语义的 uid**（网易云用户 ID / B 站 mid），与数据库无关，不算重复
  - `backend/integrations/netease_music.py:327` 字段名 `expires_at_hint` 是网易云 API 返回字段，与本库 expires_at 列无关

**结论行**：活·`user_id`（DB schema 真列），消费者遍布所有 query 的 WHERE / JOIN / FK；单用户退化(values 恒为 `default`，但 schema 约束 + 全部 query 都用它)→ NOT dead。`uid` 不是列、是 alias，本身无对应可"判活/判死"的对象。

### 2.3 `memory.type`（CHECK fact/instruction/emotion/activity/daily 五分类）

**活·多消费者**

写入约束：`backend/database/models.py:145` `CheckConstraint type IN (...)` (5 类) + DB schema 同步约束。
写入路径：
- `backend/database/services.py:104` (ORM 写时必传)
- `backend/memory/extractor.py:230-267` (server-side 抽取，写 `type` + `entry_type` 双列；commit bfcd821 后 prompt 决定 entry_type，map 回 5 类 type 兼容旧 UI)
- `backend/routes/memory_api.py:204` UI PATCH 可改

读取/筛选消费者（活）：
- `backend/database/services.py:324` `query.where(Memory.type == type)` (search_memory 显式过滤)
- `backend/agents/chat.py:752,790` 序列化给 LLM 的 memory 列表 (key `"type"`)
- `backend/proactive/engine.py:702-703` **关键筛选**：`for m in mems if m.type == "instruction"`（only instruction 类型注入主动陪伴 prompt）
- `backend/agents/memory.py:70` LLM tool 读取
- `backend/routes/memory_api.py:119,166,216` UI 响应

**结论**：活·多消费者，主动陪伴依赖 `type == "instruction"` 过滤是硬依赖。

### 2.4 `memory.entry_type`（v3.5-chunk10 四分类 fact/preference/event/commitment）

**活·窄消费者**

列定义：`backend/database/models.py:170` `entry_type = Column(Text, nullable=True)`（无 DB-level CHECK）。
注释（同文件 L167-169）明确说明：与 5 类 `type` 不重叠，由 chunk-10 worker 写入。

写入路径：
- `backend/memory/extractor.py:230,250,267` (raw INSERT 同时写 `type` + `entry_type`；`_TYPE_LEGACY_MAP` 反向兼容 5 类)
- `backend/database/migrations/v3_5_chunk10_memory_structured.py:11,66` migration 加列

读取消费者（活）：
- `backend/utils/memory_entry_validator.py:131` extractor 校验时读 `entry_type`
- `backend/routes/memory_api.py:124` UI 响应序列化

⚠️ 注意：未发现 `entry_type` 出现在任何 query `WHERE entry_type == ...` 过滤——目前**只是被读出/写入但未做筛选维度**。但代码注释说明它是 chunk 10 引入的"四分类"待后续用 → 不能判死。
**结论**：活·窄消费者(写+读+UI 序列化，但目前没有 WHERE 维度筛选)。与 `type` 并存属 RT-2 "双 type cruft" 已记录于 §Z.5.1。

### 2.5 `supersede` 相关机制

**零活消费者·疑似死(待人工核，本轮不处理)**

字面 `supersede / supercede` 共出现 6 次，**全部在注释 / docstring / 模块说明文本中**：
- `backend/database/services.py:171` docstring 中提及 "v4-beta Stage 2 supersede+墓碑 Phase B"
- `backend/database/migrations/v4_0_0_memory_tombstone.py:5/29/30` 注释明确说"**本刀不实现 supersede**"
- `backend/main.py:139/383` 注释引用 "supersede+墓碑" 这个项目名
- `backend/memory/tombstone.py:1` docstring 同上引用项目名
- `backend/config/prompt_manager.py:3` 注释中 "supersedes this module" 是英语动词用法（v4 segment 1 替代旧模块），与 memory supersede 无关
- `backend/agents/chat.py:642`、`backend/utils/memory_entry_validator.py:276` 注释引用项目名

`grep -E "def .*supersede|supersede.*=|supersede\("` 全库**输出空** —— 无函数 / 赋值 / 调用。

与 DESIGN.md §Z.5.1 RT-3 "supersede 自身机制未实现"原文一致：所述"新事实搬到上海不会找/标/替老事实住北京，两条共存" → 代码无对应 supersede 替换逻辑实现。

**结论**：零活消费者·疑似死(待人工核，本轮不处理)。
注：项目"supersede + 墓碑"已实现"墓碑"那一半（§2.6），supersede 那一半留下一刀。

### 2.6 `tombstone / memory_tombstone / 墓碑`

**活·完整链路就位（DB 表暂未建）**

DB 表（migration 已就位但 DB 未跑过一次）：
- `backend/database/migrations/v4_0_0_memory_tombstone.py:50` `CREATE TABLE IF NOT EXISTS memory_tombstone` + L61 索引
- `backend/main.py:140-141, 388` 启动调 `migrate_v4_0_0_memory_tombstone()` 注册
- ⚠️ `momoos.db .tables` 实测无此表（详 §1.0）

写入：
- `backend/database/services.py:186` `INSERT INTO memory_tombstone` (delete_memory 同事务，仅 expires_at IS NULL 才写)

读取 / 决策（活消费者）：
- `backend/memory/tombstone.py:51` `async def is_tombstone_suppressed(content, user_id)` —— dup-check helper
- `backend/memory/tombstone.py:73` `SELECT content, embedding FROM memory_tombstone WHERE user_id=?`
- `backend/memory/tombstone.py:91` 精确 content 命中 → return True
- `backend/memory/tombstone.py:114` cosine ≥ 0.92 → return True

调用消费者（活）：
- `backend/agents/chat.py:644-652` save_memory tool 写入前 check → tombstone-suppressed status
- `backend/utils/memory_entry_validator.py:276-280` extractor 写入前 check

**结论**：活·完整链路就位（双 write 入口经 `services.delete_memory` 单点收口写墓碑；双 consumer 在 chat.save_memory 和 extractor.validator 两处都 dup-check）。
唯一缺口：真 DB 文件无表，需 backend 启动跑 migration——commit 3f3be08 ship 后未真机回归一次。⚠️ 待真机回归。

### 2.7 `characters.yaml` 读取 vs DB persona 读取（Plan B 现行 / Plan C 未做）

**两源并存·三路 fallback 全活**

DB 真持有（8 行）：
```
id=1   Momo           （persona 文本 = yaml "默认"条目 ChatAgent 原文，即 X.8 Mai 借壳前状态）
id=2   八重神子
id=3   荧
id=4   凝光
id=5   神里绫华
id=99  一般路过猫娘
id=100 祥子-test
id=101 樱岛麻衣
```

yaml 真持有（5 条目）：`八重神子 / 默认(ChatAgent fallback) / 荧 / 凝光 / 神里绫华`；`default_character: 默认`。
**yaml 中无 Momo / 猫娘 / 祥子-test / 樱岛麻衣**（即 DB 比 yaml 多 4 个 character_id：1/99/100/101）。

读取路径（chat.py `_build_messages` 一图三路）：

| 路径 | 优先级 | 源 | 触发条件 |
|---|---|---|---|
| v4 renderer | 1（主） | `character_personas` 表(`is_active=1`) | `character_id is not None` 且 renderer 不抛 |
| legacy DB persona | 2（fallback） | `characters.persona` 文本 | renderer fallthrough（无 active variant / migration 没跑 / jinja 失败） |
| yaml prompt_manager | 3（兜底） | `characters.yaml "默认"` | `character_id is None` 或 DB persona 空 |

证据：
- `backend/agents/chat.py:1130-1170` renderer path（segment 1 主入口）
- `backend/agents/chat.py:1316-1334` legacy DB persona 路径
- `backend/agents/chat.py:1330-1334` yaml fallback (`prompt_manager.get_prompt`)
- `backend/config/prompt_manager.py:30` yaml 读取入口
- `backend/agents/prompt/persona_loader.py:79-130` v4 renderer 读 `character_personas` 表

其它 yaml 用途（仍活）：
- `backend/tools/builtin.py:20,63` LLM tool `switch_character` 校验 character_id 合法性（仍参照 yaml characters 名）
- `backend/database/migrations/v4_persona_thickening_segment1.py:48` migration 一次性从 yaml backfill 到 `character_personas` 表

**结论**：
- 双源并存：v4 segment 1 已 ship → DB persona 是 LLM 主源；yaml 仍是 fallback + tool 校验源
- Plan B（DB 主源 / yaml fallback）= 现行
- Plan C（全员迁 DB / yaml 退役）= 文档承诺未做
- **不是死代码**：yaml 3 路 fallback 中真正用到的是第 3 路兜底，但 LLM tool switch_character 校验仍硬依赖 yaml
- DB 比 yaml 多 4 个角色（id 1/99/100/101），意味着 LLM `switch_character(character_id=99/100/101/1)` 若校验依赖 yaml characters 名 → 可能 raise（需 §3 核实校验逻辑细节）。⚠️ 待人工核 builtin.py:20-63 校验是用 character_id 还是 name 字典。

### 2.8 §2 小结

| 符号 | 结论 |
|---|---|
| `expires_at` | 活·部分接线（read+UI write+墓碑 gate 都活；chat/extractor 写端不传值） |
| `uid` vs `user_id` | `uid` 不是列、是 alias；`user_id` 是真列，活·单用户退化(NOT dead) |
| `memory.type`（5 类 CHECK） | 活·多消费者（含主动陪伴 `m.type=="instruction"` 硬筛选） |
| `memory.entry_type`（4 类） | 活·窄消费者（写+读+UI 序列化；无 WHERE 维度筛选；RT-2 已记录） |
| `supersede 机制` | 零活消费者·疑似死(代码层面 0 函数 0 调用；RT-3 已注释明示) |
| `tombstone / memory_tombstone` | 活·完整链路就位（DB 表暂未实建，待真机 migration 跑一次） |
| `characters.yaml` vs DB persona | 双源·三路 fallback 全活；Plan B 现行，Plan C 未做；LLM tool `switch_character` 校验源待 §3 核实 |

⚠️ 本节累计 ⚠️ 待人工裁决：
1. 真 DB 实测有无 `expires_at IS NOT NULL` memory 行（§2.1）
2. memory_tombstone 真机 migration 是否成功执行（§2.6）
3. LLM tool `switch_character` 是否还能正确处理 DB 多出 4 个 yaml 没有的角色（§2.7 → §3 跟进）

---

## 第3节 功能面双向对账（只读）

### 3a 代码侧实际接线的 capability / tool / route

#### 3a.1 FastAPI 路由（从 `backend/main.py:911-934` 实读）

20 个 router include 全部 prefix=`/api`（除 ws）：
```
health, config, memory, conversations, characters, persona, users, live2d,
backgrounds, tts, observability, capabilities, integrations, webhooks,
briefing, character_state, activity, mcp, ai_providers, ws (websocket, no prefix)
```

对应 `backend/routes/*.py` 文件 21 个，全部已 wired。`__init__.py` 0 字节，无 routes。

#### 3a.2 ToolRegistry（LLM function-calling）

两路注入：
1. `backend/tools/registry.py:95-96` 内置 2 个直接注册：`switch_character` / `clear_short_term`
2. `backend/capabilities/registry.py:118` capability with `Consumer.CHAT_AGENT` → 派生 OpenAI schema → `ToolRegistry.register()`

#### 3a.3 CapabilityRegistry（`@register_capability` 装饰器）

实测 56 个 capability，分布：
```
backend/capabilities/activity.py          3   (get_today_summary / get_recent_apps / search_history)
backend/capabilities/apple_calendar.py    4   (today/upcoming/create/delete)
backend/capabilities/bilibili.py         11   (search_video / get_video_info / search_user / get_user_videos / hot_videos / get_ranking / get_subtitles / get_my_history / get_my_followings / get_later_watch / get_favorites)
backend/capabilities/calendar.py          2   (today_events / upcoming_events)
backend/capabilities/character_state.py   3   (get_state / set_activity / intimacy_decay)
backend/capabilities/clipboard.py         3   (get_recent / summarize / translate)
backend/capabilities/docx_ops.py          3   (create / read / append)
backend/capabilities/google_calendar.py   2   (today_events / upcoming_events)
backend/capabilities/media_control.py     5   (next_track / previous_track / play_pause / now_playing / set_volume)
backend/capabilities/netease_music.py     7   (daily_recommend / personal_fm / play_song / play_playlist / play_playlist_by_id / like_current / search)
backend/capabilities/netease_playback.py  6   (local_play_song / local_play_playlist / local_pause / local_resume / local_stop / local_next_in_queue)
backend/capabilities/screen.py            4   (get_active_app / get_browser_url / get_browser_content / get_active_document)
backend/capabilities/time_capability.py   1   (time.now)
backend/capabilities/xiaohongshu.py       1   (xhs.parse_url)
backend/proactive/snooze_capability.py    1   (proactive.snooze_wake_call)
```

#### 3a.4 主动陪伴 trigger / cron 注册（`backend/main.py:680-836` 实读）

trigger 类（实存）：
- `WakeCallBriefingTrigger`（独立 base）
- `MorningBriefingTrigger`（独立 base）
- `LunchCallTrigger / DinnerCallTrigger / BedtimeChatTrigger / LongIdleTrigger`（继承 `InviteTriggerBase`）
- `ActivityProactiveTrigger`（独立 base，由 activity_smart 调起）

stage 2 注册表 `_STAGE1_SENTINELS / _STAGE2_BUILDERS`（`backend/proactive/triggers/_stage2_registry.py`）实际登记 5 个：`bedtime_chat / wake_call / lunch_call / long_idle / dinner_call`。`morning_briefing` **不走 stage 2**（单方面播报，无邀请回复链）。

cron / interval 注册条件：
- lunch_call_weekday / lunch_call_weekend（`_lunch_mod._enabled()` 为真）
- dinner_call（`_dinner_mod._enabled()` 为真）
- bedtime_chat（`_bedtime_mod._enabled()` 为真）
- long_idle_check interval（`_long_idle_mod._enabled()` 为真）
- mode 互斥：`proactive.mode == "wake_call"` → 注册 `WAKE_CALL_CRON_JOB_ID`；`mode == "morning_briefing"` → 注册 morning 那条；`mode == "off"`/未知 → 都不注册（避免两条 8:00/9:00 撞车）

#### 3a.5 8 个真 character vs 资产实测

| id | name | live2d_model 字段 | 实际 splash | yaml 条目 | 备注 |
|---|---|---|---|---|---|
| 1 | Momo | `hiyori` | (空) | ❌ yaml 无 | persona 文本 = yaml "默认" ChatAgent；X.8 Mai 借壳的 cid=1，DESIGN.md §Z.8 中文 voice |
| 2 | 八重神子 | `yae` | /splash-art/2.png | ✅ | live2d 字段已配但 frontend/public/live2d/ 实际只见 `hiyori / yae` 两目录，**yae 真就位** |
| 3 | 荧 | (空) | /splash-art/3.png | ✅ | 无 live2d 绑定 |
| 4 | 凝光 | (空) | (空) | ✅ | 无 live2d 绑定，无 splash |
| 5 | 神里绫华 | (空) | (空) | ✅ | 无 live2d 绑定，无 splash |
| 99 | 一般路过猫娘 | (空) | /splash-art/99.png | ❌ yaml 无 | |
| 100 | 祥子-test | (空) | /splash-art/100.png | ❌ yaml 无 | |
| 101 | 樱岛麻衣 | `hiyori` | /splash-art/101.png | ❌ yaml 无 | persona JSON spec 在 docs/mai_prompt.md；DESIGN.md §X.8 借壳 cid=1 描述 → 但 DB 中 id=1 是 Momo 而非 101 = ⚠️ 命名漂移 |

`frontend/public/live2d/` 实际目录：`core / hiyori / yae`（hiyori = Live2D 官方示例；yae = 八重神子模型；core = pixi-live2d-display 运行时核心，不是模型）。
`frontend/public/splash-art/` 实际文件：`_placeholder.png / 2.png / 3.png / 99.png / 100.png / 101.png`（git 状态：2/3/99/100/101 均 untracked，详 §0.3）。

### 3b 代码存在但文档没提（反向扫）

下面所述以代码事实为准；本节列出**文档没单独说明、但代码已实成接线**的项。

#### 3b.1 ToolRegistry 内置 2 tool — switch_character / clear_short_term

`backend/tools/registry.py:95-96` 直接登记到 ToolRegistry（不走 capability registry，schema 直接 hardcode 在 `backend/tools/builtin.py`）。
DESIGN.md / DESIGN_LITE / ROADMAP / README 检索 `switch_character`：
- DESIGN.md：4 处提到（其中 §X.8 借壳描述、tool 列表里的隐含、capability tagging 讨论）
- 但 **没有显式说明它和其它 56 个 capability 是分开走两套 register 流程的**——内置 2 tool 不在 CapabilityRegistry，因此 `/api/capabilities` 列表中不会出现。

⚠️ 这是文档没正式登记的小事实：UI capability 面板拿不到这两条，但 LLM 仍可调。

#### 3b.2 stage 2 registry 5 个 trigger

`_stage2_registry.py` 注册的 5 个 stage-2 builder（`wake_call / lunch_call / dinner_call / bedtime_chat / long_idle`）是邀请-回复链路的核心机制。
DESIGN.md L2189-2244 详细描述了 sentinel registry，ROADMAP.md L585-647 描述了五 trigger pack 与测试覆盖。**已被文档化**。

#### 3b.3 ActivityProactiveTrigger（活动感知）

`backend/proactive/triggers/activity.py` + `activity_smart.py`（19KB）+ `activity_judge.py`（13KB）+ `activity_watcher.py`（22KB）+ `activity_monitor.py`（20KB），合计 ~70KB 活码。
DESIGN.md / ROADMAP 中找得到 v3.5 chunk 8a 引用，但描述简略。⚠️ 文档化程度不及代码体量。

#### 3b.4 conversation_summary 表 + summary worker（v4.0.0 b91505a）

新表 `conversation_summary` 在 §1.16 已记录。worker `backend/memory/summary.py` + 注入 chat 上下文路径。
DESIGN.md §Z.5.1 表格列了 commit `b91505a` "有界滚动摘要层"，**这一项已文档化但简略**——未明确表名 / 触发条件 / 重压缩策略与 schema。

#### 3b.5 v4_0_0_memory_tombstone migration + tombstone helper

`memory_tombstone` 表 + `backend/memory/tombstone.py` dup-check + `services.delete_memory:184-196` 双删入口写墓碑 + chat.py 与 memory_entry_validator 双消费者。
DESIGN.md §Z.5.1 commit `3f3be08` "墓碑表" 一行列出。**机制层文档化偏简略**：表 schema / dedup 双比对（精确 + cosine≥0.92）/ user_id 维度但跨 character 的设计、未在主文档里展开。

#### 3b.6 voice_aliases / character_personas_builtin_seed / character_states 等表

`voice_aliases`（4 行真数据）由 `backend/database/voice_aliases.py` 管理；DESIGN_LITE / DESIGN 主架构图未画出，仅在 v4 persona 段落与 TTS bugfix-3.3 commit 说明里出现。
`character_personas_builtin_seed`（8 行）restore_to_builtin 回滚源；DESIGN.md F1 段提到。
`character_states`（20 行；含测试残留）`backend/database/services.py:643-689` 完整 CRUD；DESIGN.md §F2 v3-G chunk 3b 描述。

#### 3b.7 mcp 三表（credentials/client_state/tool_state）

DESIGN.md / ROADMAP 描述 MCP client 整体，但**三个 DB 表的字段级文档**主要落在代码注释。

### 3c 文档声称存在但代码未实现 / 被改没（细分两类）

#### 3c.1 未实现 / 落空（文档提了但代码从没接成）

| # | 文档位置 | 文档说法 | 代码事实 | 处置方向 |
|---|---|---|---|---|
| 1 | DESIGN.md L1296 表 | "加藤惠（外部资产）✅ 6 个 expression（Cubism 2 .moc，pixi-live2d-display 不支持）" | frontend/public/live2d 目录无 kato/加藤惠 任何文件；characters DB 无加藤惠条目 | 文档标注**未实现/挂个人 backlog**；DESIGN.md L1369-1371 已自陈"格式锁死无解" |
| 2 | DESIGN.md §F1 "其他 cid 是空骨架...八重等" | "cid 2/3/4/5/99/100 空骨架，v4.1 F1 仿 mai_prompt 逐个灌真 persona" | DB 真出：八重(id=2) 有 yae live2d；其余 3/4/5/99/100/101 多数 live2d 字段空。仅"是空骨架"层面属实，但**101=樱岛麻衣**未在 DESIGN.md §F1 列入；§Z.8 仅讨论 cid=1 借壳 | 文档需对齐：把"101=樱岛麻衣 (实测条目+/splash-art/101.png+live2d=hiyori)"补回 §F1 列表；同时澄清 cid=1=Momo 与 cid=101=樱岛麻衣的关系（X.8 借壳是 cid=1，并非 cid=101） |
| 3 | DESIGN.md §X.8 / Z.8 Mai 借壳描述 | "characters.id=1 配置...樱岛麻衣 persona 借 Momo 壳" | DB 实测：id=1 name=Momo persona=yaml "默认" ChatAgent 原文（即 Z.8 措辞"借壳前状态"）；id=101 name=樱岛麻衣 single splash + hiyori live2d | 文档需对齐：两个 id 同时存在的关系、当前主用谁；Z.8 又说"identity / Tier-1 / Tier-2 全部不动"——而 DB id=1 的 persona 是 ChatAgent 原文，未见 Mai 真 persona 落 DB → **本节代码层 grep 无法确认"借壳"是否仍在生效**。⚠️ 待人工核 |
| 4 | DESIGN.md §F1 / DESIGN_LITE Live2D 段 | "v4-beta 主推 Mai 单角色，其他角色 v4.1 接 Live2D" | 现状：Hiyori（id=1 Momo / id=101 樱岛麻衣 都绑）+ yae（id=2 八重）就位；3/4/5/99/100 全无绑定 | 文档对现状无明确措辞——若把"Mai 单角色"理解为只用 cid=1 → 与 cid=2 八重 yae 已实接矛盾；若理解为"主推 cid=1，其他模型存在但非主推"→ 与 DB live2d 字段一致。**待人工裁决文档措辞** |
| 5 | DESIGN.md §X.8 / Z.5.1 RT-3 | "supersede 自身机制" 列为表层债 | 全库 0 函数 0 调用（§2.5 已实锤） | 文档已对齐（"未实现"已标注），无需调整；保留为 RT-3 表层债 |
| 6 | DESIGN_LITE.md "voice_samples" Tier-1 字段 | "Tier-1 7 字段必填...voice_samples" | DB character_personas 8 行均 NOT NULL 必填这 7 列，但 default 真用户实测无明显数据（本节 grep 没遇 voice_samples 数据展示 path 失败）；UI persona_api.py 提供 CRUD | 文档与代码一致；待真机 UI 检查 voice_samples 是否在 LLM prompt 路径被消费（§2 grep 仅看到 persona_loader 加载，未验是否真注入到 prompt） |

#### 3c.2 曾有被改没 / 孤儿残留（代码有注册残留但永不触发）

| # | 文档位置 | 文档说法 | 代码事实 | 处置方向 |
|---|---|---|---|---|
| 1 | DESIGN.md §X.8 早期 prompt_manager 路径 | "早期 prompt_manager 只读 characters.yaml，UI 切角色不影响 system prompt" | chat.py:1310-1334 实读：renderer → DB persona → yaml fallback 三路；**prompt_manager 仍为最后兜底 + LLM tool 校验源**。非孤儿 | 文档已记录"修法"，与代码现状一致 |
| 2 | DESIGN.md `backend/config/prompt_manager.py:3` 注释 | "⚠️ DEPRECATED — v4 persona engineering segment 1 supersedes this module" | 模块仍被 chat.py:1333 + builtin.py:20-63 调用，未真删除 | 文档说"deprecated"，代码仍活——这是**写在代码注释**里的 deprecated 标记，不属 DESIGN/DESIGN_LITE/ROADMAP/README 任一项。处置方向="标注 deprecated 时点 + 兜底用途，待 Plan C yaml 退役同步真删" |
| 3 | DESIGN.md / DESIGN_LITE Plan B/Plan C persona 双源 | "Plan B 现行 / Plan C(全 DB)未做" | §2.7 已实锤三路 fallback。Plan C 真未做 → 此项**未删未孤儿**，是文档承诺的待办 | 处置方向="文档承诺保留，等真做 Plan C 时再调" |
| 4 | DESIGN.md L4671-4673 §Z.4 对话 UI 统一 | "删右上角独立'历史'入口 + 删旧浮现台词气泡 + 删 ChatHistoryDrawer" | 本节未深入 frontend 代码扫描；DESIGN.md 是"已删"叙述，git log 显示 f79495c commit 已 ship。**前端代码现况是否真无 ChatHistoryDrawer 残留**未实测 | ⚠️ 待人工核（前端 src 扫一遍 ChatHistoryDrawer / 浮现气泡组件） |
| 5 | DESIGN_LITE.md / DESIGN.md token 治理 §Z.6 | "short_term 硬性 cap 30 + tool_result 截断 4000" | 代码：`backend/memory/short_term.py` SHORT_TERM_MAX, `backend/agents/chat.py` dbc851a tool_result trim。本节 grep 未细查具体值，仅文档对齐 | 文档对齐，不需调 |

#### 3c.3 LLM tool switch_character 校验源（§2.7 跟进）

`backend/tools/builtin.py:21` `prompt_manager.switch_character(user_id, character_id)` 调旧 prompt_manager 的 switch_character → 仅认 yaml 5 个角色名（八重神子/默认/荧/凝光/神里绫华）。

⚠️ **DB 中 character_id=1/99/100/101 是 yaml 没有的 4 个 character**——LLM 若用 `switch_character(character_id="Momo")` 或 `character_id="樱岛麻衣"` 等 → `prompt_manager.switch_character` 返 False → tool 抛 `ValueError("未知角色")`。

这是真实存在的 silent 漂移：**Live2D 模型与 splash 已就位的角色（Momo/猫娘/祥子-test/樱岛麻衣）通过 LLM tool 切角色路径切不动**，必须走前端 UI 直接改 active character_id 才能切到这 4 个。

DESIGN.md / DESIGN_LITE / ROADMAP / README 未单独提此漂移。
处置方向="待人工核：需要让 switch_character 校验源切到 DB characters 表，或者文档明示 'switch_character LLM tool 仅认 yaml 5 个名字'"。

### 3d §3 小结

- 真接线统计：**21 FastAPI router + 58 LLM tool（2 内置 + 56 capability）+ 7 trigger 类 + 5 stage-2 builder + 4-5 cron job（按 enabled/mode 决定）**
- 8 个 character vs 5 个 yaml 条目漂移已逐行实证（§3a.5）
- 主要漂移集中 4 处：
  1. id=1 Momo 与 id=101 樱岛麻衣 / X.8 Mai 借壳的命名关系（⚠️ 待人工核）
  2. switch_character LLM tool 仅认 yaml 5 个名（cid=1/99/100/101 切不动）
  3. 加藤惠 Live2D（Cubism 2 格式锁死，DESIGN.md 已自陈无解）
  4. supersede 机制（§2.5 实锤未实现，文档已记录为 RT-3 表层债）

⚠️ §3 累计 ⚠️ 待人工裁决：
1. id=1 Momo / id=101 樱岛麻衣 命名关系（§3c.1 #3）
2. "Mai 单角色"措辞与 cid=2 八重 yae 已接的实情对齐（§3c.1 #4）
3. switch_character 校验源 / 文档措辞二选一（§3c.3）
4. 前端 ChatHistoryDrawer 残留是否真已清（§3c.2 #4）

---

## 第4节 漂移台账（综合，逐行）

格式：{文档位置 | 代码实际 | 分类 | 处置方向 | 风险/可逆性}
分类四桶：① 陈旧文档 / ② 未文档化新功能 / ③ 死schema/孤儿列(疑似，待人工核) / ④ 已删/未实现功能但文档仍在
"处置方向"只写方向（如"文档需对齐现实"/"待人工核是否清理"），不写"已可删/应删"。
DESIGN.md 显式历史档案双层保留政策：台账只记录，不建议改历史段。

### 4.1 逐行台账

| # | 文档位置 | 代码实际 | 分类 | 处置方向 | 风险/可逆性 |
|---|---|---|---|---|---|
| 1 | DESIGN.md L4687 "14 sentinel commit 未动" | 文档未列出具体 14 个 sha；仓库内仅此一处出现该字面 | ① 陈旧 / 描述不完整 | 文档补齐具体 sha 清单（候选 A/B 见 §0.5） | 低；纯叙述补齐，不影响代码 |
| 2 | DESIGN.md §Z.5.1 RT-4 "expires_at 未正经接线，所有 caller 全传 None" | chat/extractor 写端确为 None；LLM tool + UI 两路接受非 None；read 端 active_only 过滤 + 墓碑 gate 全活 | ① 陈旧 / 部分准确 | 文档对齐：写端不传值是 chat/extractor 主路，但读端与 UI 写端都活 | 低 |
| 3 | DESIGN.md §Z.5.1 RT-2 "双 type 列 cruft" | 实证：`type` 5 类有 WHERE 维度筛选（proactive `m.type=="instruction"`）；`entry_type` 4 类仅读+写无 WHERE | ① 陈旧准确 / 仍是表层债 | 文档保留 RT-2 标记，等下一刀处理 | 低；不动 |
| 4 | DESIGN.md §Z.5.1 RT-3 "supersede 自身机制未实现" | 全库 0 函数 0 调用，全部 supersede 字面在注释 / docstring | ④ 未实现 / 文档已自陈 | 文档保留 RT-3 标记 | 零；纯未实现，无残留 |
| 5 | DESIGN.md §Z.5.1 RT-5 "墓碑 check 无类型感知" | tombstone.py 仅按 user_id 维度查；不读 entry_type / type；可能误压新建时效提醒 | ④ 未实现 / 已表层债入册 | 文档保留 RT-5 标记 | 中；行为风险已记录待 v4.1 |
| 6 | DESIGN.md §Z.5.1 commit 3f3be08 "墓碑表" | 表 schema、cosine≥0.92 阈值、user_id 维度跨 character、双消费者位置等技术细节未在主文档展开 | ② 未文档化新功能（机制细节） | 文档可补技术细节（user_id 跨 character、cosine 阈值、双消费 path） | 低；纯文档补全 |
| 7 | DESIGN.md §Z.5.1 commit b91505a "有界滚动摘要层" | conversation_summary 表 schema、Qwen3.5-Flash 配置点、触发条件、重压缩策略等技术细节未展开 | ② 未文档化新功能（机制细节） | 文档可补技术细节 | 低 |
| 8 | DESIGN.md §X.8 / §Z.8 "Mai 借壳 characters.id=1" | DB 实测：id=1 name=Momo persona=yaml "默认" ChatAgent 原文；id=101 name=樱岛麻衣 单独存在 | ① 陈旧 / 命名漂移 ⚠️ | 文档需对齐：两个 id 同时存在的关系、当前主用谁 | 中；可能涉及前端 / LLM tool / 默认 character_id 解析 |
| 9 | DESIGN.md §F1 "cid 2/3/4/5/99/100 空骨架" | DB 真出：3/4/5/99/100/101 多数 live2d 字段空；八重(id=2) 有 yae live2d | ① 陈旧 / 列表缺 101 | §F1 列表补 101 = 樱岛麻衣 | 低 |
| 10 | DESIGN.md L1296 表 "加藤惠 Cubism 2 .moc" | 仓库 frontend/public/live2d 无 kato 任何文件；DB 无加藤惠条目；DESIGN.md L1369-1371 已自陈"格式锁死无解" | ④ 未实现 / 文档已自陈 | 文档保留个人 backlog 标记 | 零 |
| 11 | DESIGN.md §Z.4 "删 ChatHistoryDrawer / 浮现台词气泡" | 后端代码无关；前端代码本节未实测扫，git log 显示 f79495c 已 ship | ④ 已删 / 文档已记录；前端清况未实测 | ⚠️ 待人工核前端 src 实际清况（grep ChatHistoryDrawer） | 低；纯前端核实 |
| 12 | DESIGN.md / DESIGN_LITE Plan B / Plan C persona 双源 | §2.7 三路 fallback 实证；Plan C 未做 | ① 文档承诺保留 | 文档保留 Plan C 待办 | 零 |
| 13 | DESIGN_LITE / DESIGN.md token 治理 §Z.6 "30 turn cap + 4000 字符 tool_result 截断" | 代码 SHORT_TERM_MAX + dbc851a 已 ship；本节未实测具体值 | ② 文档对齐，未实测具体常量 | ⚠️ 待人工核常量真实值与文档一致 | 低 |
| 14 | DESIGN.md §F1 Mai 单角色定位 | DB 实测 cid=2 八重已 yae live2d 接，cid=1 借 hiyori；非 cid=1 only | ① 陈旧 / 措辞需更精确 | 文档微调："主推 cid=1 borrow 壳；其他模型存在但非主推" | 低 |
| 15 | DESIGN.md §F1 / X.8 LLM tool switch_character | builtin.py:21 走旧 prompt_manager → 仅认 yaml 5 角色名；DB 多 4 个角色（id=1/99/100/101）切不动 | ③ 接线断裂 / 文档未提 | 文档措辞 OR 代码切到 DB 校验源；本轮记录不改 | 中；用户体验风险 |
| 16 | DESIGN.md §1.0 / DESIGN_LITE 主架构图 voice_aliases 表 | 表存在 4 行真数据；主架构图未画 | ② 未文档化新功能 | 主架构图补 voice_aliases 表 | 低 |
| 17 | DESIGN.md / DESIGN_LITE mcp 三表（credentials / client_state / tool_state） | 三表 schema 与字段在代码注释，主文档未展开 | ② 未文档化新功能（字段细节） | 主文档可补三表字段 | 低 |
| 18 | DESIGN.md §Z.5 audit "默认用户 memory 表 0 行" | 实测仍 0 行（fix 链 ship 后 mtime 早于最后 fix；真机回归未跑） | ① 陈旧 / 待真机回归 | 文档已声明"功能待真机回归" | 零 |
| 19 | DESIGN.md §F2 v3-G chunk 3b character_states 表 | 20 行 vs 8 character → 12 行测试残留疑似 | ③ 测试残留数据（非孤儿列） | ⚠️ 待人工核：要不要清测试残留 | 低；纯数据，活码不动 |
| 20 | DESIGN.md §F1 character_personas_builtin_seed 用途 | 8 行就位；restore_to_builtin 调用源 persona_api.py:400 | ② 文档化偏简略 | 主文档补 restore_to_builtin 工作流 | 低 |
| 21 | DESIGN.md §Z.5.1 RT-1 "异构表 memory 混存持久事实 + 时效提醒未拆" | 实证：单表混存（expires_at NULL / not NULL）；RT-1 已表层债入册 | ① 陈旧准确 / 已表层债 | 保留 | 零 |
| 22 | DESIGN.md §Z.9 "DB 备份系列" | 实测 7 个 .db.backup_* + 1 个 before-mai-injection 全为 untracked（§0.3） | ① 文档说明与现状一致 | 文档/policy：是否保留全部备份 → ⚠️ 待人工核 | 低 |
| 23 | DESIGN.md §Z.5.1 fix 链对真 git diff 顾问核验 | git log 8 条 + DESIGN.md 表 7 条对得上；docs 2d7b793 在表外是 docs commit | ① 文档与现状一致 | 保留 | 零 |
| 24 | DESIGN.md L4694 commit f712625 / 42d1800 "extractor pointer clamp" | 实证：extractor.py:354-356 clamp 调用 + routes/conversations_api.py:138 UPDATE memory_extractor_state 都已就位 | ① 文档与现状一致 | 保留 | 零 |
| 25 | DESIGN.md §X.8 "voice_model.tts_language 'ja' → 'zh' / voice 'longyumi_v3'" | 本节未实测 characters 表 voice_model JSON 内容 | ① 待实测 | ⚠️ 待人工核 DB cid=1 voice_model JSON 真实值 | 低 |
| 26 | DESIGN_LITE.md L84 Tier-1 7 字段 "voice_samples" 含义 | character_personas schema NOT NULL 必填；LLM 注入路径在 persona_loader → renderer | ② 仍需验注入路径 | ⚠️ 待人工核 voice_samples 是否真出现在 LLM prompt 中 | 低 |
| 27 | DESIGN.md §Z.5.1 commit bfcd821 "抽取 prompt 重平衡" | 代码已就位（entry_type=4 类 + recurrence 仅 confidence）；功能实证待真机回归 | ① 文档与现状一致 | 保留，等真机回归 | 零 |
| 28 | DESIGN.md ActivityProactiveTrigger / activity_smart / activity_judge / activity_monitor / activity_watcher（70KB 活码） | 主文档化偏简略 | ② 未文档化（深度） | 主文档可补活动感知架构图 | 低 |
| 29 | DESIGN.md §X.8 / Z.8 references README L29 "Mai (cid=1, riding the Momo shell + Hiyori model, with a Sakurajima Mai persona core)" | DB id=1 是 Momo，persona 是 yaml 默认 ChatAgent 原文（无 Mai 内核进 DB） | ① README 与代码漂移 / 命名 ⚠️ | README 措辞与 DB 实情对齐 | 中 |
| 30 | DESIGN.md §五·补 滚动摘要 + DESIGN_LITE 主流程 | DESIGN_LITE 主架构图未画 conversation_summary 表 / summary worker | ② 未文档化 | DESIGN_LITE 主图可补一笔 | 低 |

### 4.2 桶分布统计

| 桶 | 条数 | 主要议题 |
|---|---|---|
| ① 陈旧文档 | 14 条（#1, #2, #3, #8, #9, #11(部分), #12, #14, #18, #21, #22, #23, #24, #27, #29——按多桶归在 ① 的） | 大多是文档与代码事实需要措辞对齐，不需删 schema |
| ② 未文档化新功能 | 8 条（#6, #7, #13, #16, #17, #20, #28, #30） | 主要是 b91505a / 3f3be08 / mcp 三表 / voice_aliases / activity_smart 一族文档欠债 |
| ③ 死schema / 孤儿列（疑似） | 2 条（#15, #19） | #15 是 LLM tool 校验断裂；#19 是测试数据残留 |
| ④ 已删/未实现但文档仍在 | 4 条（#4, #5, #10, #11(已删部分)） | RT-3 supersede / RT-5 墓碑无类型感知 / 加藤惠 / ChatHistoryDrawer 待前端核 |

注：本台账有些条目跨桶——上表只取主桶。

### 4.3 §4 风险结论

- **本轮零代码 / 零 schema / 零 commit / 零 stash 动作**——纯文档台账，可逆性 = 100%
- 桶 ① 与桶 ② 的所有项可在用户醒后逐项 review，不影响代码运行
- 桶 ③ 的 2 条建议优先讨论（switch_character LLM tool 校验源 = 真用户体验风险）
- 桶 ④ 的 RT-3/RT-5 已是表层债入册，本轮不动；加藤惠是个人 backlog；ChatHistoryDrawer 是 ⚠️ 待人工核

---

## 第5节 续接点

### 5.1 完成度

| 节 | 状态 | 说明 |
|---|---|---|
| §0 基线核真 | ✅ 完整 | 14 sentinel sha 候选 A/B 列出；其余基线全健康 |
| §1 真 schema + 写入源 | ✅ 完整 | 22 表全数实证；memory_tombstone 表暂未在 DB 实建（migration pending） |
| §2 列消费者 grep | ✅ 完整 | 7 个符号全数 grep 实证 |
| §3 capability/tool/route 双向对账 | ✅ 完整 | 21 router + 58 tool + 7 trigger + 8 character 全数实证 |
| §4 漂移台账 | ✅ 完整 | 30 行台账，4 桶分类 |
| §5 续接点 | ✅ 完整（本节） | |

### 5.2 醒后第一步建议

按风险/可逆性排序，建议依次：

1. **真机回归一次 backend 启动**——验证：
   - `v4_0_0_memory_tombstone` migration 真跑过 → `momoos.db .tables` 出现 `memory_tombstone`
   - default 用户产生新 memory 行（验证 §Z.5.1 fix 链真有效）
   - DB 备份动作：先 cp 一份 momoos.db.backup_audit_$(date) 再启动
2. **§3c.3 LLM tool switch_character 校验源**——这是真用户体验风险，建议先讨论"改代码"还是"改文档措辞"
3. **§3c.1 #3 / §4 #29 命名漂移**——cid=1 Momo 与 cid=101 樱岛麻衣 的关系（X.8 Mai 借壳是哪个？）需要拍板，否则后续文档对齐做不下去
4. **§4 桶 ② 未文档化新功能**——8 条文档欠债，照表逐项补主文档；本轮已给位置和说明
5. **§4 桶 ① 陈旧文档** 14 条措辞对齐——按 DESIGN.md 双层保留政策，仅补"对齐说明段"或新增 §Z.10+，**不动历史段**
6. **测试残留清理（pending_briefings 234 / memory 9 / character_states 多余 / users 18 测试 uid）**——是否清需要先决定保留 momoos.db 的 forensic 价值

### 5.3 ⚠️ 待人工裁决项汇总清单

按发现节序：

| # | 出处 | 议题 | 当前状态 |
|---|---|---|---|
| 1 | §0.5 | 14 sentinel commit 具体 sha 集合（候选 A/B 二选一或第三种） | 本轮不动任何 commit；醒后明确即可 |
| 2 | §1.0 / §1.17 / §2.6 | memory_tombstone migration 真机回归是否能成功执行 | 待真机启动 backend 一次 |
| 3 | §1.8 | pending_briefings 234 行测试残留 + memory 9 行测试残留 + character_states 测试 character_id 残留 + users 18 测试 uid → 是否清 | 本轮不删任何行 |
| 4 | §1.9 | character_states 20 行 vs 8 character → 测试残留细节 | 同上 |
| 5 | §2.1 | 真 DB 实测有无 `expires_at IS NOT NULL` memory 行 | 本轮未跑这条 query；醒后可一行 sqlite3 实测 |
| 6 | §2.7 / §3c.3 | LLM tool `switch_character` 校验源（yaml-only）vs DB 多 4 个角色（id=1/99/100/101）切不动 | 改代码 or 改文档措辞二选一 |
| 7 | §3a.5 / §3c.1 #3 / §4 #8 #29 | cid=1 Momo 与 cid=101 樱岛麻衣 的关系 + X.8 Mai 借壳到底是 cid=1 还是 cid=101 | 文档措辞待对齐 |
| 8 | §3c.1 #4 / §4 #14 | DESIGN.md §F1 "Mai 单角色"措辞与 cid=2 八重 yae 已接现实的对齐 | 文档微调 |
| 9 | §3c.2 #4 / §4 #11 | 前端 ChatHistoryDrawer / 浮现台词气泡 残留是否真已清干净 | 待前端 src 实测扫一遍 |
| 10 | §4 #13 / §4.3 | SHORT_TERM_MAX 真实常量与 dbc851a 4000 字符截断是否仍是文档号称值 | 一次 grep 实测即可 |
| 11 | §4 #22 | DB 备份 7 个 + before-mai-injection 共 8 个，是否全保留 | policy 决定 |
| 12 | §4 #25 | DB cid=1 voice_model JSON 真实值（tts_language + voice） | 一行 SELECT 即可 |
| 13 | §4 #26 | voice_samples 是否真在 LLM prompt renderer path 被注入 | 一次 grep 实测即可 |

### 5.4 本审计报告的边界声明

- **只读代码 + 只写本文件** —— DESIGN.md / DESIGN_LITE.md / ROADMAP.md / README.md / frontend/README.md / 任何代码 / momoos.db / .gitignore 文件 / stash / commit / push 全程未动
- **不写"应删 / 可删 / 必须改"** —— 报告最强措辞为"零活消费者·疑似死(待人工核，本轮不处理)"
- **可逆性 = 100%** —— 删本文件即可恢复 audit 前的仓库状态（本文件之外无任何改动）

---

**审计完成。所有 ⚠️ 项均已记录，不做任何代码 / DB / 文档侧动作。**

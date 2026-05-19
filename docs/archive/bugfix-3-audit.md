# Bugfix-3 Audit — AI Providers 三类统一管理(LLM / ASR / TTS)+ 用户自定义

> 本 stage = audit-only。不动代码,推荐 sub-stage 拆分等用户拍板后再实施。

---

## §1 LLM 现状

**Provider 列表**:`config.yaml::available_models[]` —— 当前 2 项:
- `openai/qwen3.6-plus` (display="Qwen3.6 Plus", tier=stable)
- `openai/qwen3.6-max-preview` (display="Qwen3.6 Max", tier=preview)

**Active 选择**:`config.yaml::default_model` 一项字符串(LiteLLM model id)。

**API**:`backend/routes/settings_api.py`
- `GET /api/settings/model` → `{current, available[]}`
- `POST /api/settings/model {model}` → 校验在 available 里 → 写回 yaml → `reload_config_yaml()` → 即时生效
- 校验严格:body.model 必须在 available_ids 里, 否则 400

**调用链**:
- `backend/llm/client.py::call_llm/stream_llm` → `litellm.acompletion(model=resolved_model, ...)`
- DashScope 走 OpenAI-compatible 通道:`api_base = settings.dashscope_base_url`, `api_key = settings.dashscope_api_key` (从 .env 读)
- 其他 provider (openai/anthropic/deepseek):LiteLLM 自动从 env 变量 (`OPENAI_API_KEY` 等) 读 —— 这些 env 来自 pydantic `Settings` (`.env` 文件) 自动 export

**关键约束**:用户在 UI 加一个新 provider 必须能配 `(api_base, api_key)` 显式传给 LiteLLM,不能只靠 env。要么 call_llm 改成显式 kwargs,要么 LiteLLM provider override 注册。

**切换是即时的**(POST 后下一条消息生效, 无 restart)。

---

## §2 ASR 现状

**Provider**:**唯一** —— faster-whisper local (`backend/asr/whisper.py`)。
- 模块 singleton `whisper_asr`, 首次调用 lazy load
- 不支持运行时切换 model size(load 后固定; 改 size 必须重启)

**配置**:`.env` via pydantic `Settings`:
- `whisper_model: "tiny"|"base"|"small"|"medium"|"large-v3"` (默认 small)
- `whisper_device: "cpu"|"cuda"|"auto"` (默认 cpu)

**VAD**(non-Whisper):
- 前端侧:`frontend/src/hooks/useAudio.ts` 用 Web Audio API 算 RMS,store 持 `vadThreshold` (1-100) + `silenceTimeoutMs` + `muteWhileSpeaking`
- localStorage 持久化(老 AsrVadSection wrapper hydrate)
- Whisper 侧:`vad_filter=True` per-call(faster-whisper 内置 silero VAD, 与 FE VAD 平行)

**调用**:`whisper_asr.transcribe_b64(b64_audio, language)` 同步阻塞在 ThreadPoolExecutor。

**provider 抽象**:**没有**。要加多 ASR 必须新建 dispatcher。

---

## §3 TTS 现状

**Providers** (`backend/tts/`):
- `CosyVoiceProvider` (DashScope cloud, 商用主线)
- `EdgeTTSProvider` (微软免费 TTS, fallback)
- `SoVITSProvider` (自部署本地, 通过 `settings.sovits_api_url`)

**配置**:
- `config.yaml::tts.provider` = 全局默认 provider
- `config.yaml::tts.cosyvoice.{model, default_voice, instruct_supported}` = CosyVoice 子配置
- `config.yaml::tts.available_voices.{provider}[]` = voice 列表 (id/label/traits/instruct/ssml)
- **Per-character override**: `characters.voice_model` 字段存 JSON 字符串:
  ```json
  {"provider": "cosyvoice", "voice": "longyumi_v3", "instruct_supported": false}
  ```

**API**:`GET /api/tts/voices` 序列化 `available_voices`, 给 CharacterPanel 下拉数据。

**调用链**:
- `backend/tts/__init__.py::get_tts_engine(voice_model)` 解析 JSON → 选 provider class
- 包一层 `_PreprocessingEngine` (剥 emotion/thinking/etc tag)
- `engine.synthesize(text, emotion)` → bytes

**Provider 抽象**:**已有** (`TTSBase`) ✓。新加 TTS provider 只需:
1. 继承 `TTSBase` 写一个 class
2. 在 `_build_engine` 加 if-elif
3. config.yaml 加 voice 列表

**热切换**:每 synth 调用都 fresh build,即时生效。

---

## §4 凭证 / API key 机制

**两条独立路径**(没统一):

### 路径 A: `.env` via pydantic `Settings`(冷加载)
- `deepseek_api_key`, `openai_api_key`, `anthropic_api_key`, `dashscope_api_key`, `dashscope_base_url`, `serper_api_key`, `sovits_api_url`, `netease_music_u`, `whisper_model`, `whisper_device`, `database_url`
- 进程启动时一次读取,运行时不变;UI 无法编辑
- LiteLLM 通过环境变量自动 pick up(因为 Settings 字段大写名导出到 process env)

### 路径 B: `mcp_credentials` SQLite 表(热加载)
- Schema: `(server_name, key_name, value, updated_at)` UNIQUE(server_name, key_name)
- **明文存** (V1; ROADMAP backlog 升 OS keyring)
- CRUD: `backend/mcp/credentials.py` 全 async
- 用法:MCP server 启动子进程前 `get_env(server_name)` 注入 subprocess env
- UI: `ExtensionsSection` → `CredentialsModal` → POST upsert → DB

**${VAR} 模板**:MCP 走的是 env 注入(子进程视角),不是模板替换。LLM provider 不走 subprocess,要换模式:把 api_key 显式传 LiteLLM kwargs。

**核心问题**:**LLM 凭证目前没有 DB 路径**。要让用户从 UI 加新 provider,要么:
- 扩 mcp_credentials 表 namespace(`server_name='ai_provider:openai-custom'`)
- 或新建 `ai_provider_credentials` 表(语义更清晰)

---

## §5 改造影响面

### Backend 改造

| 区域 | 现状 | 改造需求 |
| ---- | ---- | -------- |
| LLM provider list | yaml `available_models` 固定列表 | DB `ai_providers` 表(id/category/display/api_base/credentials_ref/active/builtin) |
| LLM call dispatch | LiteLLM 全靠 env 自动 | 显式 `api_base/api_key/model` kwargs 传 acompletion, 从 DB 查 active provider |
| ASR provider | 单 whisper 写死 | 新增 ASRBase abstract class + dispatcher (类 TTSBase) |
| ASR model 切换 | 重启才生效 | reload model on config change (代价:GPU memory 反复 load) |
| TTS provider 抽象 | ✅ 已有 TTSBase | 改 voice 列表数据源 yaml → DB |
| 凭证存储 | 二分:env / mcp_credentials | 新表 `ai_provider_credentials` 或复用 mcp_credentials namespace |

### Frontend 改造

| 区域 | 现状 | 改造需求 |
| ---- | ---- | -------- |
| AI Providers section | 3 子 tab(LLM/ASR/TTS) 包老 ModelSection / AsrVadSection / TtsSection | 重写:provider 列表 + add/edit modal + 凭证表单 + active toggle |
| 老 ModelSection | radio 选 builtin | 列表 + 行内 "active 切换" + "编辑" 按钮 |
| 老 AsrVadSection | 录音模式/阈值/超时 4 个控件 | VAD 控件仍留(走 client-side),provider 切换是新增 |
| 老 TtsSection | 单 "启用 TTS" toggle | 全局 default provider 选择 + voice 库管理 |

### Migration

- 一次性把现有 `config.yaml::available_models` + tts builtin 配置 seed 进新表,标 `builtin=True`
- 凭证从 .env 迁移到 DB?**不建议** —— .env 是 12-factor 标准, 容器/CI 友好。新表只存 user-added provider 的 credentials, builtin 仍读 env(LiteLLM 老路径不变)

---

## §6 Sub-stage 推荐

### Option A:一气呵成(2-3 工作日, 高风险)
单 commit:DB 表 + migration + 后端 dispatcher 重构 + 前端重写 + builtin seed。

**风险**:
- LLM call path 是聊天主链路, dispatcher 改动出 bug 会 break 所有对话
- 单 commit 难以二分定位回归
- UI 大改 + 后端大改同时上,真机找 bug 难

### Option B:三 sub-stage 拆分(推荐)

#### **Bugfix-3.1 — Backend foundation**(~1 工作日)
- Migration: 新表 `ai_providers (id, category, slug, display_name, api_base, model, extra_json, credentials_ref, is_active, is_builtin, created_at, updated_at)` + 索引 (category, is_active)
- Migration: 新表 `ai_provider_credentials (provider_id, key_name, value, updated_at)` (复用 mcp_credentials 加密策略 = 明文 V1)
- 一次性 seed: 把 yaml `available_models` 写进表, `is_builtin=True`
- 新增 REST: `GET/POST/PATCH/DELETE /api/ai_providers`, `GET/POST/DELETE /api/ai_providers/{id}/credentials`
- 改 `call_llm`: 先查 DB 取 active LLM provider, 若有 api_base/api_key 则显式传给 acompletion, 否则走老 env 路径(向后兼容)
- ASR/TTS dispatcher 不动(下一 stage)
- 老 yaml `default_model` + `/api/settings/model` 保留**只读 fallback**(DB 无 active 时退到 yaml)

**验收**:真机走查 builtin 切换不破坏聊天;用户 add custom provider 走 API curl 测可用。
**UI = no-op,老 SettingsPanelLegacy 派生的 ModelSection 仍工作**。

#### **Bugfix-3.2 — UI rewrite**(~1.5 工作日)
- 重写 AI Providers section(SettingsPanelV2 → Capabilities → AI Providers)
- 3 tab (LLM / ASR / TTS) 内每个:
  - Provider 列表 + 行内 active 切换 + edit/delete 按钮(builtin 禁删,只能 disable)
  - "+ 添加自定义 provider" 入口 → 弹 modal 填 (display_name, api_base, model, api_key)
  - 凭证字段不回显 value(仅显示 configured ✓)
- 老 AsrVadSection VAD 4 控件保留 ASR tab 下方(VAD 是 client-side, 不进 provider 范畴)
- 全局默认 TTS provider:用列表行的 active toggle
- 移除 SettingsPanelLegacy 对 ModelSection / TtsSection 的 export(确认 V2 不再用)

**验收**:真机 add OpenAI custom provider + 切 active → 下一条聊天用新 provider; ASR 暂只展示 whisper(单 provider 不可切, 等 3.3 加 dispatcher)。

#### **Bugfix-3.3 — ASR provider dispatcher + sunset 老路径**(~0.5 工作日)
- 新增 `ASRBase` abstract + factory `get_asr_engine(provider_id)`
- 改 ws.py 调用点走 dispatcher
- 第二 ASR provider 占位:Whisper API (cloud) — 真接通可选, 至少 schema 跑通
- 删 yaml `available_models`(DB 已是 source of truth, 老路径 fallback 移除)
- 删老 `/api/settings/model` 与 `legacy ModelSection` 的所有引用

**验收**:builtin whisper 仍工作;custom ASR provider 走 API 至少注册成功;yaml 减肥。

### 推荐:**Option B**

**理由**:
1. **隔离风险面**:3.1 后端只改 LLM 主链路(聊天命脉), UI 不动 → 容易回归测试。3.2 UI 大改完全不碰 backend 主链, fail safely. 3.3 在两边都稳定后再 sunset 老路径。
2. **真机测试节奏匹配**:每 sub-stage 都有独立可验收点(curl / 真机走查 / sunset 验证),Skyler 一次只 review 一个 layer。
3. **Schema 评审窗口**:3.1 留出时间让用户检视新表 schema(尤其 `extra_json` 字段语义), 避免 3.2 提交后 schema 锁死。
4. **回退路径明确**:3.1 commit 出 bug → revert 单文件回到 yaml 路径; 3.2 出 bug → 仍可用 SettingsPanelLegacy 切 model(因为 fallback 还在); 3.3 是最后一里, 此时整套已稳。

---

## 关键技术决策点(等 Skyler 拍板)

> 这 5 个问题影响实施细节,**audit 不预设答案**,等用户回看后再 implement。

### Q1: provider 元数据存哪?
- **A** (推荐): 新 DB 表 `ai_providers` — 加新 provider 是 INSERT,UI 直接 CRUD,schema 规整
- **B**: 扩 config.yaml::available_models 加字段 — 烧瓶式,user-added 也写 yaml 文件,API key 入 yaml 不安全
- **混合**: builtin seed 一次性写 DB, user-added 也入 DB; yaml 只作 builtin seed 源(可只读)

### Q2: 凭证机制?
- **A** (推荐): 新表 `ai_provider_credentials (provider_id, key_name, value, updated_at)`, schema 跟 mcp_credentials 平行
- **B**: 复用 `mcp_credentials` 表,用 `server_name='ai_provider:{id}'` 命名空间 — 省一张表,但 server_name 一字段二语义
- **C**: 加密上 OS keyring(macOS Keychain)— ROADMAP backlog,本 stage 暂不;V1 同 mcp 走明文 SQLite,文件级 OS 权限隔离

### Q3: 切换 active 是否即时?
- **A** (推荐): **是**,与现有 `/api/settings/model` 行为一致(POST 后下一条消息走新 provider,无 restart)。实现:每次 call_llm 都查 DB(无缓存),开销 ~1ms 可接受
- **B**: 缓存 active provider in-memory, change 通知用 pub/sub —— 复杂,无明显收益

### Q4: 老 ModelSection / AsrVadSection / TtsSection 共存策略?
- **A** (推荐): 3.1 共存(老节点仍工作,DB fallback yaml);3.2 老节点从 SettingsPanelLegacy 解除 import;3.3 sunset legacy 文件
- **B**: 3.1 立即下线老 UI — 风险大,回归找不到地方测

### Q5: Builtin seed 列表初始包括哪些?
- **LLM** (来自现有 yaml + 业界主流):
  - openai/qwen3.6-plus, openai/qwen3.6-max-preview (沿用 yaml)
  - deepseek/deepseek-chat (env 已有 key)
  - openai/gpt-4o, openai/gpt-4o-mini (用户能配 key 就用)
  - anthropic/claude-sonnet-4-5, anthropic/claude-opus-4-7 (高端选项)
- **ASR**: 只一个 builtin:faster-whisper local (model size 作 `extra_json`)
- **TTS**: cosyvoice / edge / sovits 三个 builtin(沿用现有 provider class)

---

## Audit 结论简要

- **§1 LLM**: yaml-driven 固定列表 + LiteLLM env-driven, 切换热但不可扩
- **§2 ASR**: 单 whisper 写死, 无 dispatcher 抽象
- **§3 TTS**: ✅ provider 抽象已存在(`TTSBase`), 只需把 voice 列表数据源从 yaml 挪 DB
- **§4 凭证**: env (LLM cloud) vs `mcp_credentials` 表(MCP) 二分, AI Provider 缺路径
- **§5 改造**: 后端需 dispatcher 重构 LLM + ASR (TTS 复用), 前端需 AI Providers 重写

**推荐 Option B 三 sub-stage 拆分**, 总工作量 ~3 工作日, 风险面隔离, 真机验收节奏好。

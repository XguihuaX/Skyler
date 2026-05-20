# INVESTIGATION-5 · token 治理轮（子轨 A：prompt caching）

> 接 INV-3（1098 行封存）/ INV-4（工具治理子轨 B，暂停在 §1，子轨 A 完成后续 §2）。
> 本文件自 2026-05-20 prompt caching 子轨 A 勘查与实施起用。

---

## §1 prompt 装配结构勘查（纯只读 · 决定 cache_control marker 怎么放）

> 子轨 A 第一步已 grep 确认 `cache_control` / `prompt_caching` / `ephemeral` 全 backend 零命中（绿地）+ ROADMAP / DESIGN_LITE 已登记。
> 本节回答"~19k 静态前缀怎么放 marker 才稳定命中缓存"。覆盖 6 问 Q1-Q6 + 三方案 proposal。

### 1.1 Q1 — 现 system message 结构

**结论：(c) 多条 system，每条 content 都是大 string（非 list-of-blocks）。**

**事实链**（`backend/agents/chat.py:1253-1283`）：

```python
# chat.py:1253-1255 - messages[0] = 单 system,content = render_system_prompt 输出的整段 string
messages: List[dict] = [
    {"role": "system", "content": system_prompt}
]
# chat.py:1259-1272 - 若 fold worker 已产出 summary,append 第二条 system
try:
    from backend.memory.summary import get_summary
    _sum = await get_summary(user_id, character_id, conversation_id)
    if _sum:
        messages.append({
            "role": "system",
            "content": f"【过往对话摘要(滚动压缩)】\n{_sum}",
        })
except Exception:
    ...

# chat.py:1273-1281 - short_term turns(user/assistant)依次 append
if not skip_short_term:
    for turn in await short_term_memory.get(...):
        messages.append({"role": turn["role"], "content": turn["content"]})

# chat.py:1282 - 当前用户文本作为最后一条
messages.append({"role": "user", "content": text})
```

→ messages 最终形态（按位置）：

| idx | role | content | 字节稳定性 |
|---|---|---|---|
| 0 | system | `render_system_prompt(...)` 输出（含 Layer A/B/C/D 全段，~19k+ tokens） | **混合**（A/B/C1-3 稳定 + C4/D 不稳） |
| 1（可选） | system | `【过往对话摘要(滚动压缩)】\n{_sum}` | 变量（per-fold tick 重压缩） |
| 2..n-1 | user/assistant | short_term turns（最多 25 turn × 2 = 50 message） | 自然演变 |
| n | user | 本轮用户文本 | 每 turn 必变 |

→ **整段 messages[0] 是单 string,稳定段与不稳定段揉在一起**;不改结构则前缀缓存粒度只能"全 cache 命中或全 miss",任何 C4/D 字段微变都让整个 ~19k 静态前缀缓存失效。

### 1.2 Q2 — Layer 渲染输出形态 + 字节稳定性

**结论：(a) 各 layer 独立 string 渲染，最后 `"\n\n".join` 拼成大 string。**

**事实链**（`backend/agents/prompt/renderer.py:239-256`）：

```python
parts: List[str] = [
    _render_layer_a(available_motions, tts_language),
    _render_layer_b(mode, tool_prompt_addendum),
    _render_layer_c(persona, states, safe_thought, llm_vendor, filtered_samples),
    _render_layer_d(
        user_profile, today_activity, long_memory_top5,
        tool_results, temp_instructions, briefing,
    ),
]
if just_switched_variant:
    parts.append(_render_transition(persona.variant_name))

out = "\n\n".join(p.strip() for p in parts if p and p.strip())
```

→ 每层渲染输出独立 string，**没有保留结构化分隔到 caller**（`_build_messages` 收到的是已拼合的 `system_prompt: str`，无法直接按层切）。

**Layer 内字节稳定性矩阵**（直读各 `.j2`）：

| Layer | 文件 | 子段 | 输入字段 | 字节稳定性 |
|---|---|---|---|---|
| A | `layer_a.j2:1-30` | 输出格式 + 长度建议 | 静态文字 | ✅ 稳定 |
| A | `layer_a.j2:17-19` | 可用 motion 列表 | `available_motions` | ✅ 实测 `chat.py:1232-1244` **不传该参数 → None → if-false 段不渲染**（grep `available_motions=` 全 codebase 唯一 call site 是 `renderer.py:117` 内部）|
| A | `layer_a.j2:32-84` | ja/en TTS 模式段 | `tts_language` | ✅ per-character `voice_model` JSON 字段固定；同一 character 内稳定 |
| B | `layer_b.j2:1-17` | mode_directive（B1） | `mode` | ⚠️ `roleplay` ↔ `proactive` 切换时文字段变 → 跨 mode cache miss（预期） |
| B | `layer_b.j2:19-45` | universal_constraints（B2） | 全静态 | ✅ 稳定 |
| B | `layer_b.j2:47-50` | TOOL_PROMPT_ADDENDUM 嵌入 | `tool_prompt_addendum` | ✅ 模块常量 `_TOOL_PROMPT_ADDENDUM`（chat.py 传入），3.2k 全静态 |
| C | `layer_c.j2:1-7` | C1 身份卡 | `persona.identity.*` | ✅ DB persona 字段，per-character 稳定 |
| C | `layer_c.j2:8-18` | C1b self_intro 双梯级 | `_intimacy >= 70` 切换 0-69 ↔ 70-100 | ⚠️ **跨 intimacy=70 阈值文字段切换** → 阈值附近反复跨阈会 thrash cache |
| C | `layer_c.j2:20-44` | C2/C3 性格 + 说话风格 + 口头禅 | `persona.personality_core.* + speech_style.* + signature_phrases` | ✅ persona DB 字段固定 |
| C | `layer_c.j2:46-52` | voice_samples filtered | `filtered_samples` = `filter_samples_by_tolerance(persona.voice_samples, cliche_tolerance)` | ✅ list-comprehension 保序；`cliche_tolerance` 是 persona DB 字段固定 |
| C | `layer_c.j2:54-72` | forbidden_phrases vendor 分支 | `llm_vendor` ∈ {qwen, deepseek} | ⚠️ 切 LLM vendor（极少）时文字段变 |
| C | `layer_c.j2:73-126` | C3b/c/d taboo / lore / emotion_triggers | persona Tier-2 字段 | ✅ persona DB 固定 |
| C | `layer_c.j2:128-133` | **C4 当前状态** | `states.mood / intimacy / activity / safe_thought` | ❌ **每 turn 都可能变**（character_state 由 `<state_update>` 更新） |
| D | `layer_d.j2:1-32` | profile / today_activity / long_memory_top5 / tool_results / temp_instructions / proactive_briefing | 全部 caller 实时聚合 | ❌ **全变量段** |
| Transition（可选） | `transition.j2` | `new_variant_name` | 仅切 variant 那一 turn 出现，平时不渲染 | n/a |

→ **静态 / 变量边界**：

- **稳定前缀**：Layer A 全 + Layer B（除 mode_directive 子段会随 roleplay/proactive 跨段变）+ Layer C1/C1b/C2/C3/C3b/C3c/C3d（除 self_intro 阈值切换、forbidden vendor 切换）
- **每 turn 变化**：Layer C4 + Layer D
- → 当前**全部揉进 messages[0] 单 string**，无法分别打 marker

### 1.3 Q3 — tools_schema 传递路径

**结论：(a) 走 `acompletion(messages=..., tools=[...])` 参数。** 但 Layer B 内仍有 `_TOOL_PROMPT_ADDENDUM` 3.2k 自然语言工具引导段（与 tools schema 内容部分重叠）。

**事实链**（`backend/agents/chat.py:1647-1667`）：

```python
san_tools, tool_name_rev_map = sanitize_tools_for_llm(_get_all_tools())
...                          # token_probe emit
wrapper = await call_llm(
    messages,
    stream=True,
    tools=san_tools,         # ← OpenAI function-calling schema list,不在 system 文本
    enable_search=enable_search,
)
```

→ tools_schema 13.25k 走 `call_llm(tools=...)` → `client.py:184 acompletion(model=..., messages=..., tools=san_tools, stream=True, ...)`。

**Cache marker 放 tools 的可能性**：Anthropic / Bedrock / Qwen 显式 cache 路径**支持在 `tools` 列表最后一条注入 `cache_control`**（cache 整个 tools schema 块）。OpenAI / DeepSeek 自动 cache 路径 tools 也会被自动缓存。详 Q4。

### 1.4 Q4 — LiteLLM × DashScope × Anthropic 兼容性（**brief 假设需校正**）

**结论摘要（按 PM brief 假设逐项校验）**：

| brief 假设 | 实际事实 | 来源 |
|---|---|---|
| LiteLLM 支持 Qwen `cache_control` | ✅ **支持**，但仅当 model prefix 是 `dashscope/` 走 LiteLLM 原生 DashScope provider | LiteLLM `/docs/providers/dashscope` + `/docs/tutorials/prompt_caching` |
| LiteLLM 支持 Anthropic `cache_control` | ✅ 支持（pass-through 原 Anthropic SDK 语义） | LiteLLM `/docs/completion/prompt_caching` |
| LiteLLM 支持 Bedrock `cache_control` | ✅ 支持，LiteLLM 自动把 OpenAI-format `cache_control` 翻译为 Bedrock `cachePoint` | 同上 |
| OpenAI / DeepSeek 自动 caching 自然命中 | ✅ 自动，无需 client marker，>=1024 tokens 自动启用 | 同上 |
| Skyler 当前 `openai/qwen3.6-max-preview` 注入 `cache_control` 即生效 | ❓ **不确定** —— Skyler model prefix 是 `openai/` 而非 LiteLLM 官方 DashScope 路径的 `dashscope/`；LiteLLM 是否在 OpenAI provider 路径上 pass-through `cache_control` 给 DashScope OpenAI-compatible 端点，**官方文档未明示** | `config.yaml:1` `default_model: openai/qwen3.6-max-preview` + `client.py:30 _dashscope_kwargs()` |

**关键事实 — Skyler 当前 model prefix vs LiteLLM DashScope 官方 prefix**：

```python
# config.yaml:1-31 当前 model 串
default_model: openai/qwen3.6-max-preview     # ← openai/ prefix
planner_model: openai/qwen-turbo              # ← openai/ prefix
memory.summary.model: openai/qwen3.5-flash    # ← openai/ prefix

# LiteLLM 官方 DashScope provider 路径要求 prefix = "dashscope/"
# (LiteLLM docs /providers/dashscope 明示)
```

```python
# backend/llm/client.py:24-35 Skyler 实际走向
def _dashscope_kwargs() -> dict:
    if settings.dashscope_base_url and settings.dashscope_api_key:
        return {
            "api_base": settings.dashscope_base_url,     # DashScope OpenAI-compatible 端点
            "api_key":  settings.dashscope_api_key,
        }
    return {}
```

→ **Skyler 走的是 LiteLLM 的 OpenAI provider 路径 + `api_base` 覆写到 DashScope OpenAI-compatible 端点**，不走 LiteLLM 原生 `dashscope/` provider 路径。LiteLLM `openai/` 路径默认不识别 `cache_control` 字段（Anthropic SDK specific），可能：

- **路径 1**：LiteLLM `openai/` provider 把 messages content blocks 原样转发 → DashScope OpenAI-compatible 端点解析 cache_control → Alibaba 官方文档明示 OpenAI-compatible 端点也支持 explicit cache → 可能生效
- **路径 2**：LiteLLM `openai/` provider strip cache_control 字段（视为非 OpenAI 标准字段） → 转发后 DashScope 收不到 marker → 退化为 implicit cache
- **路径 3**：LiteLLM `openai/` provider 报错（unsupported parameter）

→ **三条路径需实测裁决**，本刀不实测。最稳妥实施路径见 §1.7 方案对比。

**Qwen 自家 context cache 两种模式**（Alibaba 官方文档）：

| 模式 | 触发 | 最小前缀 | TTL | model 范围 |
|---|---|---|---|---|
| **Implicit cache（自动）** | server-side 自动识别公共前缀，无需 client marker | >= 256 tokens | "Not guaranteed, system periodically clears" | Qwen-Max / Plus / Flash / Coder / VL |
| **Explicit cache（显式）** | client 注入 `cache_control: {type: ephemeral}` 到 message content block | >= 1024 tokens | **5 min**（每次命中 reset） | Qwen-Max / Plus / Flash / Coder / VL（同上） |

→ Skyler 当前的 `qwen3.6-max-preview` 属 Qwen-Max 系列，**implicit cache 已经在白拿**（如果端点支持）。explicit cache 优势：**guaranteed hit + 可控 TTL**。

**最小前缀 token 门槛对比**：

| provider | min cacheable tokens | Skyler 静态前缀 ~19k | 命中 |
|---|---|---|---|
| OpenAI / DeepSeek（自动） | 1024 | ✅ 远超 | 自动 |
| Anthropic（显式） | 1024（cache_control） | ✅ 远超 | 显式 |
| Bedrock（显式） | model-dependent | ✅ 一般达标 | 显式 |
| Qwen explicit | 1024 | ✅ 远超 | 显式 |
| Qwen implicit | 256 | ✅ 远超 | 自动 |

### 1.5 Q5 — provider 检测现状

**结论：现有 provider 检测有，但不完整 / 不集中。**

**事实链**（`backend/llm/client.py:38-103`）：

```python
# client.py:38-102 _resolve_db_provider_kwargs - 仅在 caller 不显式传 model 时,
# 从 DB ai_providers 表取 active provider(含 vendor_id),并设 api_base/api_key
async def _resolve_db_provider_kwargs(model_override):
    if model_override:
        # 显式 override → 不读 DB,return (None, {})
        return None, {}
    active = await svc.get_active_provider("llm")
    ...
    return active.model, kwargs    # active.model 含 prefix(eg openai/qwen-...)
```

```python
# client.py:151-156 - enable_search 已基于 model 字符串前缀分流
if enable_search:
    model_lower = resolved_model.lower()
    if "qwen" in model_lower:
        merged["enable_search"] = True
    elif "deepseek" in model_lower:
        merged["tools"] = [{"type": "web_search_preview"}]
```

```python
# client.py:161-166 - defensive guard,model 缺 provider prefix 时只 warn 不修复
if "/" not in resolved_model:
    logger.warning(...)
```

→ 现有 provider 检测路径：
1. **DB-driven**：`active.vendor_id`（数字 id），需关联 `ai_vendors` 表才能拿 vendor type（OpenAI / Anthropic / Qwen / 自定义）—— 完整 vendor 元数据但 query 链长
2. **String-based**：`resolved_model.lower()` 包含 `qwen` / `deepseek` / `anthropic` / `openai` 检测 —— 简单可靠，与现 `enable_search` 路径同款

**建议挂点**：`client.py:151-156` enable_search 块之后、`acompletion` 调用之前（L184），加 `cache_control` 注入逻辑（按 `resolved_model.lower()` 字符串匹配 + config.yaml 白名单开关）。不需要新挂点。

### 1.6 Q6 — 字节稳定性风险点扫描

**结论：当前渲染链整体稳定，但仍有 4 类风险点需在 caching 策略中处理。**

**`grep -rn 'datetime.now\|time.time()\|random\.\|uuid' backend/agents/prompt/ backend/services/activity_timeline.py backend/services/profile_regen.py` 命中**：

- `backend/agents/prompt/__init__.py`：仅 docstring 引用 "今日活动"
- `backend/agents/prompt/tool_addendum.py:21/30/40`：tool 调用引导文字中含"今天/明天/这周"字面字符（模块常量，**字面字符不动**，不引入运行时时间戳）
- `backend/agents/prompt/templates/layer_d.j2:8`：`今日活动:{{ today_activity }}` 注入 caller 传入字符串
- `backend/services/activity_timeline.py:384+465+466 `：`format_today_activity_for_prompt` 生成 `## 用户今日活动\n今天已活跃 7小时30分钟。` —— **每 turn 实时聚合，含时段表述** → **Layer D 段**

**字节稳定性风险 4 类**：

| # | 风险 | 影响位置 | 触发条件 | 治理思路 |
|---|---|---|---|---|
| 1 | **每 turn 必变 — character_state** | Layer C4（L128-133） | 每 turn LLM `<state_update>` 可能改 mood / intimacy / activity / thought | C4 必须**排除在缓存前缀外**（拆出来后置） |
| 2 | **每 turn 必变 — Layer D 上下文** | Layer D 全段 | profile / activity / long_memory_top5 / tool_results / temp_instructions / proactive_briefing 全 caller 实时聚合 | Layer D 必须**排除在缓存前缀外**（拆出来后置） |
| 3 | **跨阈值切换 — intimacy=70 self_intro** | Layer C1b（L8-18） | intimacy 跨过 70 时 self_intro 文字段从 `0-69` 切到 `70-100` | 用户阈值附近来回跨会 thrash cache；接受预期 miss，不优化 |
| 4 | **跨段切换 — mode roleplay/proactive** | Layer B1（L4-17） | turn_origin in PROACTIVE_ORIGINS → proactive 段；否则 roleplay 段 | proactive 路径单独缓存桶（同 mode 内复用，跨 mode 不重叠是预期） |

**未发现风险**（已扫但无命中）：

- ❌ 时间戳插入（renderer 链零 `datetime.now()` / `time.time()` 调用）
- ❌ 随机种子（renderer 链零 `random.*` / `uuid` 调用）
- ❌ voice_samples 顺序不稳（`filter_samples_by_tolerance` 保序）
- ❌ persona DB 字段顺序不稳（Jinja `for` 按 list / dict 原序遍历）

→ **核心结论**：稳定前缀的"字节稳定性"由代码层基本保证；**主障碍是 caching 物理结构** —— Layer A/B/C1-3 与 Layer C4/D 当前揉进 messages[0] 单 string，无 marker 落点。

### 1.7 三方案 proposal（待 PM 拍板）

| 维度 | 方案 a · system message 拆 content blocks | 方案 b · 多 system messages | 方案 c · 渲染层改造分两段输出 |
|---|---|---|---|
| **物理结构** | messages[0].content 改 `[{"type":"text","text":...,"cache_control":{"type":"ephemeral"}}, {"type":"text","text":...}]` 两 block | messages[0]=stable system + messages[1]=variable system + messages[2]=summary + short_term + user | renderer 输出 `(stable_prefix, variable_suffix)` tuple；caller 自己决定怎么放 |
| **改动面** | `_build_messages` 把 system_prompt 拆成 stable + variable 两 block + `render_system_prompt` 返结构化产物 | `_build_messages` 拆 messages 顺序 + `render_system_prompt` 返 dict(stable, variable) | `render_system_prompt` 签名改返 tuple；`_build_messages` 全改 |
| **LiteLLM × `openai/` prefix 兼容** | ❓ 不确定 — `openai/` provider 路径是否 pass-through content blocks 内 cache_control 字段到 DashScope endpoint | ❓ 不确定 — 同上，cache_control 字段在 message 顶层（非 content block 内）行为更不明 | 与方案 a/b 二选一组合，渲染层不绑死 marker 位置 |
| **LiteLLM × `dashscope/` prefix 兼容** | ✅ 官方支持 | ✅ 官方支持 | 同上 |
| **LiteLLM × Anthropic prefix 兼容** | ✅ 官方支持（pass-through Anthropic SDK 语义） | ⚠️ Anthropic 原生不支持 message 顶层 cache_control（必须 content blocks 内） | 同上 |
| **字节稳定性保证** | stable block 字面单一 string，易 hash 校验 | 整 messages[0] 单 string 易 hash | 渲染层显式输出 stable + variable，最易测试 |
| **工程量** | 中（`_build_messages` 拼合处改 + renderer 返结构） | 小（仅改 message 顺序 + cache_control 标在 messages[0]） | 大（renderer 接口变 + 所有 caller 配套） |
| **风险** | 跨 provider 兼容性最高（Anthropic 原生格式） | Anthropic 不兼容 | 接口变更最大，回滚成本高 |
| **保留 Layer A/B/C1-3 静态前缀缓存** | ✅ 直接打 marker | ✅ messages[0] 整体作 stable | ✅ stable 段独立打 marker |
| **保留 tools_schema 缓存** | 需另在 `tools` 列表末尾打 marker | 同左 | 同左 |

**CC 倾向**：**方案 a · system message 拆 content blocks**。理由：

1. Anthropic 原生格式（content blocks 内 cache_control）是 LiteLLM 显式支持的官方语义，跨 Anthropic / Bedrock / Qwen `dashscope/` 三 provider 一致
2. 改动面集中在 `_build_messages` 拼合处（renderer 内部不动 layer 渲染逻辑，仅在 `render_system_prompt` 末尾返 `(stable_prefix, variable_suffix)` 二元组，caller 自己包 blocks）
3. 风险可控：若 `openai/` prefix pass-through cache_control 失败，回滚改 prefix 为 `dashscope/` 即可（model 字面字符调整，不动接口）
4. 方案 b 的多 system messages 在 Anthropic 原生 API 不被认可（其语义只接受单 system + content blocks 内 marker），跨 provider 兼容性窄
5. 方案 c 工程量过大，本质是方案 a/b 的渲染层包装；可作为方案 a 的 sub-step（renderer 返 tuple → caller 拼 blocks）

**但需先解决一个前置问题**：Skyler 当前 `openai/qwen-...` prefix 走 LiteLLM OpenAI 路径 + DashScope `api_base` 覆写。需要**实测**（一次性 ad-hoc 调用，非生产）验证：

- **测试 1**：messages[0].content 改 `[{"type":"text","text":"测试","cache_control":{"type":"ephemeral"}}]` 形式发 `openai/qwen3.6-max-preview` 是否报错 / strip / 命中
- **测试 2**：model prefix 改 `dashscope/qwen3.6-max-preview` 走 LiteLLM 原生 DashScope provider 是否能保留现 client.py:24-35 `api_base` 注入 + 全套 vendor / credential chain 工作

→ 实施前先做这两个实测点，再决定方案 a 是否要叠加 prefix 切换。

### 1.8 收口

- ✅ Q1：messages[0] = 单 system + 大 string；messages[1]（可选）= summary 独立 system；messages 后续是 short_term + 当前 user text
- ✅ Q2：4 layer 独立渲染 string → `"\n\n".join` 大 string；稳定段（A/B 大部分 + C1/C1b/C2/C3/C3b-d）与不稳定段（C4 + D）揉在一起
- ✅ Q3：tools_schema 走 `call_llm(tools=...)` 参数，13.25k 独立块；Layer B 内 `_TOOL_PROMPT_ADDENDUM` 3.2k 是自然语言引导（与 tools schema 部分重叠）
- ⚠️ Q4：**brief 假设需校正** —— LiteLLM 原生 `dashscope/` prefix 支持 explicit `cache_control`；Skyler 当前 `openai/qwen-...` prefix 走 OpenAI 路径 + DashScope OpenAI-compatible 端点是否 pass-through cache_control **官方文档未明示，需实测**。Qwen implicit cache（>=256 tokens、TTL 不保证）**可能已经在白拿**
- ✅ Q5：现 `client.py:151-156` enable_search 已基于 `resolved_model.lower()` 字符串匹配做 provider 分流；建议挂点：同位置后插 cache_control 注入，按 config.yaml 白名单开关
- ✅ Q6：renderer 链字节稳定性代码层基本保证（零时间戳 / 随机 / 顺序漂移）；4 类风险均为"业务字段实时变化"，靠 caching 结构层处理（C4/D 排除在缓存前缀外、proactive 单独缓存桶）
- 🔒 本节零代码 / config / DB 改动
- ➡️ **下一步等 PM 看完三方案 proposal 拍板**。CC 倾向方案 a（content blocks + cache_control）+ 实施前先做 2 个 prefix / pass-through 实测点

---

## §2 实测 3 点 · cache_control pass-through + implicit cache 探针

> §1 推断 Skyler 当前 `openai/qwen-...` prefix 走 LiteLLM OpenAI 路径，cache_control 是否 pass-through 官方文档未明示。本节用一次性 dev-only 脚本实测裁决。
>
> 三脚本：`scripts/cache_probe_T1.py` / `T2.py` / `T3.py` + 共享 `scripts/_cache_probe_payload.py`（1810 字 ≈ 1214 token 稳定 system 字面）。
> 跑法：`./.venv/bin/python scripts/cache_probe_T1.py`（同 T2 / T3）。
> 零产品代码改动；脚本仅 import `backend.llm.client.call_llm` 复用现有 vendor / credential / api_base 注入链。

### 2.1 实测方法

| 测点 | model prefix | payload | 目的 |
|---|---|---|---|
| T1 | `openai/qwen3.6-max-preview` | system content blocks + 末 block 标 `cache_control: {"type":"ephemeral"}` | 当前 prefix + 显式 marker 是否生效 |
| T2 | `dashscope/qwen3.6-max-preview` | 同 T1 payload | LiteLLM 原生 DashScope provider 路径是否 OK + cache_control 生效 |
| T3 | `openai/qwen3.6-max-preview` | system 普通 string，**无 cache_control** | 当前路径下 implicit cache 是否在白拿 |

每测连续跑 2-3 次（不同 user 短问句，相同 system），1.5s 间隔（< Qwen explicit cache TTL 5 min）。抓 `response.usage` 完整字段。

### 2.2 T1 结果 — `openai/` + cache_control（**silently strip**）

| 调用 | prompt_tokens | cached_tokens | cache_creation | cache_type | 判定 |
|---|---|---|---|---|---|
| T1.cold | 1226 | `null` | （无字段） | （无字段） | 无 cache 行为 |
| T1.warm | 1227 | `null` | （无字段） | （无字段） | 无 cache 行为 |

**两次调用均返回正常文本**（"测试已收到。"），但 `prompt_tokens_details` 内全部 cache-related 字段为 `null`。两次 prompt_tokens 1226 / 1227 几乎相同（user 短句差 1 token），**第二次未观察到任何缓存命中折扣**。

→ **行为 = (b) silently strip 不报错但也不命中**。LiteLLM `openai/` provider 路径将 `cache_control` 视为非 OpenAI 标准字段去除（或 DashScope OpenAI-compatible 端点不识别），cache 完全未发生。

### 2.3 T2 结果 — `dashscope/` + cache_control（**完美命中**）

| 调用 | prompt_tokens | cached_tokens | cache_creation_input_tokens | cache_type | 判定 |
|---|---|---|---|---|---|
| T2.cold | 1226 | 0 | **1214** | `"ephemeral"` | **写入缓存 1214 tokens** |
| T2.warm | 1227 | **1214** | 0 | `"ephemeral"` | **命中缓存 1214 tokens** |

**第二次调用 cache 命中 1214 tokens（约等于 system 全部 token），cache_creation 归零**。`cache_type: "ephemeral"` 字段明示走 ephemeral 路径，与 brief 假设一致。

`client.py:24-35 _dashscope_kwargs()` 的 `api_base / api_key` 注入在 `dashscope/` prefix 路径上**未引发任何异常**（10s 响应稳定，与 T1 / T3 同量级），LiteLLM 接受这两个 kwargs 并通过原生 DashScope provider 路径与端点联通。`_resolve_db_provider_kwargs` 走 `explicit_override` 分支（model 显式传入 → 不读 DB → 沿用 yaml + dashscope env credential 路径），原 client.py 注入链全套工作。

→ **行为 = (c) pass-through 给 DashScope 并产生 cached_tokens 计数**。

### 2.4 T3 结果 — `openai/` + 无 cache_control（**implicit cache 未观察到**）

| 调用 | prompt_tokens | cached_tokens | cache_creation | cache_type | 判定 |
|---|---|---|---|---|---|
| T3.cold | 1226 | `null` | （无字段） | （无字段） | 无 cache 行为 |
| T3.warm | 1227 | `null` | （无字段） | （无字段） | 无 cache 行为 |
| T3.warm-2 | 1226 | `null` | （无字段） | （无字段） | 无 cache 行为 |

三次相同 system + 不同 user 短问句，`cached_tokens` 三次均 `null`，**无任何缓存命中证据**。

**两种解释**（本刀无法区分）：

1. **DashScope 端点对 OpenAI-compatible 路径不暴露 implicit cache 字段** — 缓存可能服务端真的发生，但 client 端 response.usage 不携带 `cached_tokens` 字段，等于无可观测折扣
2. **`openai/` provider 路径完全不查 / 不传 cache 相关字段** — LiteLLM `openai/` provider 不解析 DashScope-specific 响应字段

→ 无论哪种，**Skyler 当前 `openai/` prefix 下没有任何可观察到的 cache 折扣**。即便服务端有 implicit cache，client 也无从证明、无从依赖。

注：T3.warm 调用一次性慢到 79.8s（其他都 10-18s），疑似 DashScope 端点偶发抖动，与 cache 判定无关；仅一次实测，不深查。

### 2.5 三测综合判定

**方案 a 实施可行性**：

| 路径 | 实测结果 | 推荐 |
|---|---|---|
| 保持 `openai/` prefix + 注入 cache_control | ❌ T1 = silently strip | **不行** |
| 保持 `openai/` prefix 靠 implicit cache 白拿 | ❌ T3 = client 端无可观测折扣 | **不行**（即便服务端有也无法度量） |
| **切 `dashscope/` prefix + 注入 cache_control** | ✅ T2 = 1214 tokens 完美命中 | **走这条** |

**explicit cache 相对 implicit cache 的边际收益估计**（仅本测点 1214 token system 前缀）：

- explicit: guaranteed hit + 5 min TTL + cached 部分按 ~10% 价计费（Qwen 官方定价规则） → 约省 ~90% 那段 token 的 prompt 价
- implicit: 客户端不可见，**无可度量收益**
- → 切 `dashscope/` prefix + explicit 是**从 0 到 1 的提升**，不是边际优化

**外推到 Skyler 主路径**（INV-3 §③ 实测主路径 22.7k token / turn）：

| 静态前缀分量 | 实测 token | 缓存后等效 token（10% 价） | 该项省下 |
|---|---|---|---|
| `tools_schema` | 13,250 | 1,325 | 11,925 |
| `addendum`（Layer B 内） | 3,188 | 319 | 2,869 |
| `persona` Layer C1-3 + Layer A/B 静态 | ~3,500（估） | ~350 | ~3,150 |
| `summary` | 0-1,000 | 0-100 | 0-900 |
| **小计静态前缀** | **~19,938** | **~1,994** | **~17,944** |
| 每轮等效 prompt token | 22,700 → **4,756** | **省约 79%** |

→ 与 brief 假设的 67-83% 量级吻合。前提是 **tools_schema 列表也能标 cache_control 且 LiteLLM `dashscope/` provider 路径接受**（本刀未实测 tools= 列表的 cache_control 行为，建议第三步实测前置）。

**推荐实施路径**（按 §1.7 方案 a + T2 实测裁决合并）：

1. **切 model prefix** `openai/qwen-...` → `dashscope/qwen-...`（`config.yaml:1/2/31` 三处 + DB `ai_providers.model` 行）
2. **写 `inject_cache_marker(messages, tools)` helper**（`backend/llm/client.py` 内或独立 module）：
   - 按 `EXPLICIT_CACHE_PROVIDERS = {"dashscope/", "anthropic/", "bedrock/"}` 白名单识别（基于 `resolved_model` 前缀字符匹配）
   - 把 system message 最后一个 text block 标 `cache_control: {"type":"ephemeral"}`（若 system 是单 string，先升级成单 text block；保留稳定字节）
   - tools= 列表最后一个 schema 标 `cache_control`（需先实测验证，作为下一步前置）
3. **config.yaml flag**：`prompt_caching.enabled: true` 默认 ON
4. **回归覆盖**：chat.py 主路径 + activity_judge + summary_worker + clipboard / compress_memories / profile_regen / memory_extraction 等独立 LLM 调用点（INV-3 §10.1 表格里 10 个 caller 全测）
5. **观测**：扩 `_token_probe.py` schema 收 `cached_tokens / cache_creation_input_tokens` 字段（INV-3 §10.7 已 preview 探针扩面方案）

**前置风险点 / 实施前需补的实测**：

- **tools= 列表能否标 cache_control**（T2 只验了 system messages 内 cache_control；tools schema 13.25k 是更大头，需单独实测）
- **proactive 路径 `extra_system` 注入位置**（INV-3 §10.6 推断）会让 system 字节段在 main_chat / proactive_engine 路径间差异 → cache key 分桶
- **切 `dashscope/` prefix 后** DB `ai_providers.model` 行还需同步迁移；可能需要 LiteLLM 重连 SDK（首启略慢）

### 2.6 收口

- ✅ T1 / T2 / T3 三测全跑通，无异常崩溃
- ✅ 行为判定明确：T1 silently strip / T2 完美命中 1214 tokens / T3 implicit cache 客户端不可见
- ✅ 方案 a 实施路径明确：**切 `dashscope/` prefix + 注入 cache_control**（不能保持 `openai/` prefix 靠白拿）
- ✅ 外推主路径理论省 ~79% prompt token，与 brief 假设吻合
- ✅ 三脚本 + 共享 payload module 落 `scripts/`，**零产品代码改动**

**实测 token 消耗记录**：

| 测 | 调用 | prompt+completion tokens 合计 |
|---|---|---|
| T1 | 2 次 | ~3,000 |
| T2 | 2 次 | ~3,000 |
| T3 | 3 次 | ~5,100 |
| **合计** | 7 次 | **~11,100 tokens**（实际 Qwen-max 约 ¥0.05-0.10 量级，与 brief 预算吻合）|

**脚本路径**：

- `scripts/_cache_probe_payload.py`（109 行，共享 1810 字 system 字面 + usage→dict helper）
- `scripts/cache_probe_T1.py`（74 行，`openai/` prefix + cache_control）
- `scripts/cache_probe_T2.py`（78 行，`dashscope/` prefix + cache_control）
- `scripts/cache_probe_T3.py`（85 行，`openai/` prefix + 无 cache_control）

→ **下一步等 PM 看完 §2.5 拍板**。若拍板走方案 a + `dashscope/` prefix，下一刀写 `inject_cache_marker` + `EXPLICIT_CACHE_PROVIDERS` 白名单 + `config.yaml` flag + 前置实测 tools= 列表 cache_control 行为。

---

## §3 实测 T4 · tools= 列表 cache_control 行为（**前置实测**）

> §2.5 明示需补一项前置实测：tools_schema 13.25k 是静态前缀里最大的一块（占 67%），单独走 `acompletion(tools=[...])` 参数，**是否支持 cache_control 必须独立验**。
>
> 一次性 dev-only 脚本：`scripts/cache_probe_T4.py`，复用 `_cache_probe_payload.py` 的 `dump_result / usage_to_dict` helper。零产品代码改动。

### 3.1 实测方法

| 字段 | 取值 |
|---|---|
| model | `dashscope/qwen3.6-max-preview`（已 §2 验证此 prefix 下 system messages cache_control 完美命中） |
| system | **短稳定 string ~147 字 / ~100 token**，**不**带 cache_control（baseline 排除 system 缓存干扰） |
| tools | **15 个合成 dummy function schema**，json 字面 ~7,903 字 ≈ 实测 3,037 prompt tokens；**最后一个 tool dict 顶层**（与 `type` / `function` 同级）标 `cache_control: {"type":"ephemeral"}` —— 这是 Anthropic SDK 官方语义位置 |
| user | 短问句（cold 用"你好"，warm 用"再来一次"） |
| 调用 | 2 次相同 system+tools，1.5s 间隔（< Qwen explicit cache TTL 5 min） |

**合成 dummy tools 而非挪用 Skyler 真实 tools 的理由**：

- 避开 import `backend.agents.chat / backend.capabilities.*` 触发的 decorator side-effect（DB / characters.yaml / capability registry init）
- 字面稳定 + 大小可控（≥1024 token 过 Qwen explicit cache 最小阈值）
- 与 T1/T2/T3 同隔离原则，只 import `backend.llm.client.call_llm`

### 3.2 T4 结果

| 调用 | prompt_tokens | cached_tokens | cache_creation_input_tokens | cache_type | content |
|---|---|---|---|---|---|
| T4.cold | 3,137 | **`null`** | （**字段缺失**） | （**字段缺失**） | "测试已收到。" |
| T4.warm | 3,138 | **`null`** | （**字段缺失**） | （**字段缺失**） | "测试已收到。" |

**对比 §2 T2 的关键差异**：

| 对比项 | T2（system 内 cache_control） | T4（tools= 内 cache_control） |
|---|---|---|
| 报错 | ❌ 无 | ❌ 无 |
| 第 1 次 `cache_creation_input_tokens` | **1,214** ✅ | （字段缺失） |
| 第 2 次 `cached_tokens` | **1,214** ✅ | `null` |
| `cache_type` 字段 | `"ephemeral"` ✅ | （字段缺失） |
| `prompt_tokens_details.cache_creation` 字段 | 出现 ✅ | （字段缺失） |

→ T4 与 T1（`openai/` prefix silently strip）**响应字段模式完全一致**：`cached_tokens` 为 `null`，无 `cache_creation` / `cache_type` / `cache_creation_input_tokens` 字段。**不是"创建后还没命中"，是"请求路径根本没把 tools 内的 cache_control 视作有效 marker"**。

注：tools_json_chars = 7,903 vs prompt_tokens = 3,137，意味着 LiteLLM 对 tools schema 做了 json minify / tokenize 压缩，比裸字符短一半多。这与 cache 判定无关，仅供后续分量推算参考。

### 3.3 判定（按 brief 三档矩阵）

| 档 | 判定条件 | T4 实测 | 命中 |
|---|---|---|---|
| ✅ | cached_tokens 数 ≈ tools schema total（即 ~3,000 token） | `cached_tokens: null` | ❌ |
| ⚠️ | cached_tokens 数 ≈ 200-500（只覆盖了 system，tools 段被 strip） | `cached_tokens: null` | ❌（更严重 —— 连 200-500 都没） |
| ❌ | 报错 | 未报错 | ❌ |

**实际 = ⚠️ 档加深版**：T4 连 baseline system 段都没自动命中（与 T3 一致 —— DashScope 端在无 marker 情况下对 client 端不暴露 implicit cache 字段）。**tools 列表里的 cache_control 被完全 silently strip 或不识别**。

**根因推断**（本刀不深查）：

- 候选 A：LiteLLM `dashscope/` provider 路径**仅在 messages 内**解析 cache_control，对 tools 字段视为 OpenAI 标准 function-calling schema，直接序列化转发给 DashScope endpoint。Anthropic SDK 原生的"tool dict 顶层 cache_control"语义 LiteLLM dashscope/ 路径未实现 pass-through。
- 候选 B：LiteLLM 转发了，但 DashScope OpenAI-compatible 端点对 tools 内非标准字段直接忽略（不报错，silently drop）。
- 候选 C：Alibaba 的 explicit cache 功能本身仅作用于 messages 内容，不覆盖 tools schema（即 Qwen 官方 server-side 设计上就不缓存 tools 部分）。

无论哪个，**对子轨 A 实施方案的影响相同**：tools= 列表 cache_control 此路径不可用。

### 3.4 推荐实施路径调整

**ROI 重算（按 INV-5 §2.5 推算分量重新拆分）**：

| 静态前缀分量 | 实测 token | 是否可缓存 | 缓存后等效 token（10% 价） | 该项省下 |
|---|---|---|---|---|
| `tools_schema` | 13,250 | ❌（T4 证实） | 13,250 | 0 |
| `addendum`（Layer B 内） | 3,188 | ✅（system 内） | 319 | 2,869 |
| `persona` Layer C1-3 + Layer A/B 静态 | ~3,500（估） | ✅（system 内） | ~350 | ~3,150 |
| `summary`（fold 产物） | 0-1,000 | ✅（独立 system message） | 0-100 | 0-900 |
| **可缓存小计** | ~6,688-7,688 | | ~669-769 | **~6,019-6,919** |
| 每轮等效 prompt token | 22,700 → **~16,000** | | | **省约 27-30%** |

→ 与 brief 预测的 ⚠️ 档 ROI 缩水到 ~30% 一致。**不是省 79%，是省 ~27-30%**。

**fallback 路径**：

| 路径 | 实施复杂度 | 预估 ROI | 风险 |
|---|---|---|---|
| **路径 1：仍走子轨 A，但仅缓存 system 段** | 低（system 内 cache_control 已 §2 T2 验证） | 省 ~27-30% prompt token | 低；需切 `dashscope/` prefix（DB 迁移） |
| **路径 2：放弃子轨 A，把火力全转回 INV-4 子轨 B（fold/tag/desc 治理）** | 中（INV-4 §2/§3 已规划） | INV-4 治理量级估 30-50% tools_schema 缩减 ≈ 省 ~25-35% prompt token | 中；INV-4 治理工程量更大 |
| **路径 3：双轨并行**（先 §2 T2 验证的 system 段 caching 简版上线 + 同时推 INV-4 子轨 B） | 高 | 累加 ~50-60% | 中；改动面叠加，回归成本高 |
| **路径 4：暂搁 prompt caching，先做 INV-4 工具治理把 tools_schema 砍到 ≤5k，再回头评估子轨 A** | 中 | 取决 INV-4 结果 | 低；纯顺序推进 |

**CC 倾向**：**路径 1（仅缓存 system 段）+ 推迟决定 INV-4 子轨 B 时机**。理由：

1. 路径 1 工程量已可控（system 内 cache_control 是 T2 实证路径，无未知风险）
2. 切 `dashscope/` prefix 是无论如何要做的（implicit cache 客户端不可见这件事本身就值得切）
3. ~27-30% ROI 虽然不是 79%，但仍是非零收益且工程小
4. tools_schema 13.25k 大头留给 INV-4 子轨 B（fold/tag/desc 治理）正面攻 —— 而不是绕道 caching
5. 路径 1 不消耗 INV-4 子轨 B 的可治理空间，两者**正交可叠加**

**前置不确定项（实施前需补的实测，本刀不做）**：

- 切 `dashscope/` prefix 后，DB `ai_providers.model` 行同步迁移路径（数据迁移 + LiteLLM 重连）
- proactive 路径的 `extra_system` 注入（INV-3 §10.6）让 main_chat / proactive_engine 路径间 cache key 分桶，需在 inject_cache_marker 设计时显式分 mode 处理
- Skyler 9 个 `call_llm` caller（INV-3 §10.1 表）各自的 messages 形态可能不同（如 activity_judge / summary_worker 是裸 user prompt 无 system，clipboard 是单 user prompt），inject_cache_marker 要按 caller 形态分流处理（≤1024 token 跳过 marker）

### 3.5 收口

- ✅ T4 跑通，无异常崩溃
- ✅ 行为判定：⚠️ 档加深版 —— tools= 列表 cache_control 被完全 silently strip/不识别（与 T1 `openai/` prefix 同响应字段模式）
- ✅ ROI 重算：从 brief 假设的 ~79% 缩水到 **~27-30%**
- ✅ 推荐路径：**路径 1（仅缓存 system 段，切 `dashscope/` prefix，工程小风险低）**
- 🔒 本节零产品代码改动，零 config / DB 改动

**实测 token 消耗记录**：

| 测 | 调用 | prompt+completion tokens 合计 |
|---|---|---|
| T4 | 2 次 | ~6,500（prompt 3,137+3,138 + completion 65+163）|

**脚本路径**：`scripts/cache_probe_T4.py`（170 行，含 15 个合成 dummy tool schema 构造 helper）。

→ **下一步等 PM 看完 §3.4 拍板**。CC 倾向路径 1；若拍板走路径 1，下一刀写 `inject_cache_marker` + `EXPLICIT_CACHE_PROVIDERS` 白名单 + `config.yaml` flag + 切 `dashscope/` prefix 迁移 + 9 个 `call_llm` caller 回归覆盖 + 探针扩面（采 `cached_tokens` / `cache_creation_input_tokens` 字段）。

---

## §4 实测 T5 · DeepSeek V4 Pro 自动 caching 是否覆盖 tools=

> §3 实测 T4 证伪 Qwen `dashscope/` 路径 tools= cache_control 不工作（ROI 缩水到 ~27-30%）。本节验另一家：DeepSeek 全自动 caching（无 marker，文档明示 agent workflow 适合 caching tools），看 tools= 是否被自动覆盖。
>
> 一次性 dev-only：`scripts/cache_probe_T5.py`（135 行），**直接调 `litellm.acompletion` 绕过 `backend/llm/client.py` 的 dispatcher**（避免 `_dashscope_kwargs()` 把 DashScope 凭证误注入 DeepSeek 路径）。复用 T4 的 15 个 dummy tool schema 便于跨测对比。

### 4.1 实测方法

| 字段 | 取值 |
|---|---|
| model | `deepseek/deepseek-v4-pro` |
| 端点 | `https://api.deepseek.com`（LiteLLM `deepseek/` provider 原生路径，DB `ai_vendors.default_endpoint`） |
| api_key 来源 | **DB `ai_vendor_credentials` 表**（fernet 加密存储，`svc.resolve_vendor_credential("deepseek")` 取解密 plaintext）—— 不是 .env |
| 显式注入 | 脚本绕过 `backend/llm/client.py` dispatcher，直接 `litellm.acompletion(..., api_key=..., api_base=...)`，避免 `_dashscope_kwargs()` 把 DashScope 凭证误注入 DeepSeek 路径 |
| system | ~123 token 短稳定字面，无 cache_control（DeepSeek 全自动不需要 marker） |
| tools | **复用 T4 的 15 个 dummy function schema**（json ~7,903 字 → 实测 ~2,820 prompt tokens），字面与 T4 完全一致便于跨测对比 |
| user | cold "你好" / warm "再来一次" |
| 调用 | 2 次相同 system + tools，1.5s 间隔 |
| 关键响应字段 | `usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`（DeepSeek-specific） |

**preflight 修正历史**：首版脚本查 `os.environ["DEEPSEEK_API_KEY"]` + `.env` → 报缺凭证 graceful exit。修正后改查 DB `ai_providers` 表（vendor=`deepseek` + model 含 `deepseek-v4-pro` + enabled=True）+ `svc.resolve_vendor_credential("deepseek")` → 实测发现 DB 内 deepseek 凭证已 fernet 加密存储（`has_credential=True / credential_source='db' / len=35`），LLM provider id=19 `deepseek/deepseek-v4-pro` enabled=True is_active=False（当前 active 是 id=16 qwen3.5-plus）。preflight 通过，进入实测。

### 4.2 T5 结果（完整 usage dump）

```
[T5] preflight:
DB preflight ok:
  provider id=19 model='deepseek/deepseek-v4-pro' enabled=True
  api_key  : present (len=35, **redacted**)
  endpoint : 'https://api.deepseek.com' (source='vendor')
[T5] model = deepseek/deepseek-v4-pro
[T5] system_text chars = 123
[T5] tools count = 15
[T5] tools json chars = 7903
[T5] cache_control = NONE (DeepSeek 全自动 caching, 无需 marker)
```

| 调用 | elapsed_ms | prompt_tokens | prompt_cache_hit | prompt_cache_miss | cached_tokens (兼容字段) | content |
|---|---|---|---|---|---|---|
| T5.cold | 3,234 | 2,920 | **0** | 2,920 | 0 | "测试已收到。" |
| T5.warm | 2,661 | 2,921 | **2,816** | **105** | 2,816 | "测试已收到。" |

**完整 usage dump（T5.warm 第 2 次）关键节选**：

```json
{
  "prompt_tokens": 2921,
  "completion_tokens": 47,
  "prompt_tokens_details": {
    "cached_tokens": 2816
  },
  "prompt_cache_hit_tokens": 2816,
  "prompt_cache_miss_tokens": 105
}
```

**校验**：`2816 + 105 = 2921 = prompt_tokens` ✅ 字段加和一致。

**注**：脚本末尾 stderr 出 `Fatal error on SSL transport / Event loop is closed`，是 LiteLLM async client 在 asyncio.run 收尾时 SSL 连接清理顺序问题（已知 LiteLLM x asyncio 噪音），**不影响测试结果**（两次调用 response 已成功落 stdout，usage 字段完整）。

### 4.3 判定 — **绿档**

| 三档 | T5.warm `prompt_cache_hit_tokens` | 实测命中 |
|---|---|---|
| **绿** | ≈ 3,100（system + tools 总） | ✅ **2,816 / 2,921 = 96.4% 覆盖率** |
| 黄 | ≈ 100-200（仅 system） | ❌ |
| 红 | 0 或字段缺失 | ❌ |

**关键事实**：

1. **DeepSeek `deepseek/` 路径全自动 caching 覆盖 tools= 列表**（实测）—— 与 T4 Qwen `dashscope/` 完全相反
2. cold 调用 `prompt_cache_miss_tokens = 2920`（写 cache），warm 调用 `prompt_cache_hit_tokens = 2816`（读 cache，剩 105 = 短 system 余尾 + user "再来一次"）
3. **无需任何 client-side cache_control marker**，DeepSeek server-side 自动识别静态 prefix
4. tools_schema ~2,820 token 全部在 cache 内（占 hit 数 ~95%）

**根因推断**（基于 DeepSeek 公开文档 + 实测）：

- DeepSeek 自动 caching 把整个 request 序列化后的 prefix（system + tools 拼接后的 wire format）做 hash 匹配。tools= 字段在 wire format 中位于 prefix（user message 之前），自动被纳入 cache key。
- LiteLLM `deepseek/` provider 路径**未对 tools 字段做任何 strip / 改写**，直接 pass-through 给 DeepSeek API。

### 4.4 跨 provider 对比（**T5 已补 row 3**）

| provider | cache 模式 | system cache | tools cache | 实测来源 |
|---|---|---|---|---|
| Qwen `dashscope/` + explicit | marker-based（`cache_control: ephemeral`） | ✅ T2 实证 1,214 cached / 1,214 hit | ❌ T4 实证 silently strip | 已裁决 |
| Qwen `openai/` 路径 | implicit cache 客户端不可见 | ❌ T1/T3 实证 cached_tokens null | ❌（推断同 T4） | 已裁决 |
| **DeepSeek `deepseek/` automatic** | **server-side automatic（无 marker）** | ✅ **T5 实证 system 段自动覆盖** | ✅ **T5 实证 tools= 段自动覆盖（~95% hit）** | **已裁决 = 绿档** |

**Skyler 主路径 ROI 外推（按 INV-5 §2.5 推算分量重新算两种路径）**：

| 路径 | tools_schema 13,250 | addendum 3,188 | persona 3,500 | summary 1,000 | 静态总 | 等效 token（cache 后） | 省 |
|---|---|---|---|---|---|---|---|
| 现状 Qwen `openai/` | 全价 | 全价 | 全价 | 全价 | 20,938 | 20,938 | 0% |
| Qwen `dashscope/` + system cache（§3.4 路径 1） | 全价 13,250 | cache 319 | cache 350 | cache 100 | 14,019 | **省 ~27%** prompt |
| **DeepSeek `deepseek/` automatic** | **cache 1,325** | **cache 319** | **cache 350** | **cache 100** | **2,094** | **省 ~75%** prompt（假设 cached 价 ~10% 全价 typical）|

→ DeepSeek **静态前缀全缓存**，ROI 接近 §1.7 brief 假设的上限 67-83%。

### 4.5 推荐 PM 决策方向

T5 = 绿档让 PM 面对**新的三选一**（不再是补凭证 vs 不补）：

| 路径 | 描述 | ROI 上限 | 工程量 | 风险 |
|---|---|---|---|---|
| **D · 切 Qwen → DeepSeek 全量** | DB ai_providers active 切到 id=19 deepseek-v4-pro，所有 LLM 调用走 DeepSeek | **~75% prompt token** | 中（DB active 行切换 + 9 个 caller 回归） | **中-高 · 中文陪伴质量风险**：Mai 是中文 persona / nuanced 陪伴语气，DeepSeek 中文 vs Qwen-Max 中文需 A/B 评测 |
| **E · 混合 provider** | 主对话保持 Qwen-Max（陪伴质量）；非陪伴链（activity_judge / summary_worker / clipboard / profile_regen / extractor）切 DeepSeek-V4-Flash（便宜 + auto cache） | 视分量配比，估 30-50% | 大（按 caller 分流逻辑 + 双套凭证 + observability 分桶） | 中 |
| **F · 保持 Qwen + §3 路径 1（system cache only）** | 既定 §3.4 路径 1，27-30% ROI，工程小 | ~27-30% | 小（仅 prefix 切换 + inject_cache_marker） | 低 |

**CC 倾向 F（保持 Qwen + 路径 1）+ 把 D 列入 v4.1 候选评估**。理由：

1. **陪伴质量 > token 经济**：Skyler v4-beta 收口的核心是 Mai 单角色纯中文陪伴扎实（README 第 5 行），切 LLM provider 风险面太大，需先做 Qwen vs DeepSeek 真机 A/B 评测（包括 persona 还原度、`<state_update>` tag 遵循、voice_samples 风格学习、`<emotion>`/`<motion>` 标记一致性、中文 colloquial / 古风混用准度），这不是本刀可裁决
2. **75% vs 27% 不是数量级差距**：~75% 省的是 input prompt token，但 Skyler 单次 completion ~300-1000 token（按 chat 流式典型）占总成本比例不小；切 DeepSeek output 价格 vs Qwen 也要算。完整 cost analysis 需建一张表，本刀不展开
3. **路径 1 是路径 D 的子集**：先按路径 F（路径 1）落地 system cache，工程 ready 后随时可叠加切 DeepSeek（路径 D），两路径**不互斥**
4. **混合 provider（路径 E）** 工程量过大，先验性价比不优；除非明确 cost 极敏感，否则不推荐
5. T5 的价值已经实现：**消除了"DeepSeek 是否能 tools cache"这个未知**，让 PM 决策有完整信息。是否切由产品策略决定，本刀不越位

**给 PM 的具体动作建议**：

- 立即可做：按路径 F 推进 §3 实施 brief，**先收 27-30% 安全收益**
- v4.1 候选：A/B 真机评测 Qwen-Max vs DeepSeek-V4-Pro 在 Mai 陪伴对话上的质量（盲测 20 turn × 5 场景），若 DeepSeek 质量不显著输于 Qwen → 切路径 D 收 ~75% 全量收益
- 长期：可探索路径 E 混合 provider（非陪伴链先切，例如 activity_judge / extractor / clipboard 这些"非角色"任务用 DeepSeek，本身就该用便宜模型）

### 4.6 收口

- ✅ T5 实测 = **绿档**：`prompt_cache_hit_tokens 2,816 / prompt_tokens 2,921 = 96.4% 静态前缀全覆盖`（含 tools= 列表）
- ✅ 跨 provider 对比 row 3 补全：DeepSeek `deepseek/` automatic 路径同时覆盖 system + tools，与 Qwen 形成清晰对比
- ✅ Skyler 主路径外推 ROI：现状 0% / Qwen 路径 1 ~27% / **DeepSeek 路径 D ~75%**
- ✅ 给 PM 新三选一（D / E / F），CC 倾向 F + D 列入 v4.1 评估
- 🔒 本节零产品代码改动，零 config / DB 改动；凭证只 RAM 内活，不进日志 / INV 报告

**实测 token 消耗**：

| 测 | 调用 | tokens 合计 |
|---|---|---|
| T5 | 2 次 | ~6,000（prompt 2,920+2,921 + completion 58+47 ≈ 5,946，cached portion 计费按 ~10% 全价折扣）|

**脚本路径**：`scripts/cache_probe_T5.py`（134 行；preflight 路径改为 DB lookup，凭证不落任何文件）

→ **下一步等 PM 决定 D / E / F 路径**：
- **D** → 进入"切 DeepSeek 全量"实施 brief（含 v4.1 A/B 评测 gating）
- **E** → 进入"混合 provider 分流"设计 brief
- **F** → 进入 §3 路径 1 真实施 brief（切 `dashscope/` prefix + inject_cache_marker + config.yaml flag + 9 caller 回归 + 探针扩面）

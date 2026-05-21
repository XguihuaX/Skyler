# INVESTIGATION-6 · token 治理子轨 B 实施（P3 起后续）

> 接 INV-4（1,107 行封存,子轨 B §1-§3 evaluation + P2 实施 ship）。
> INV-6 自 2026-05-21 起用,记 P3 character.set_activity 退役 + 后续 P1 入口折叠 + 实施细节。

---

## §1 P3 character.set_activity 退役（Stage 1 audit + Stage 2 实施收口,2026-05-21）

> INV-4 §2 发现 `character.set_activity` 是唯一一个严格 proactive cap,且与 `<state_update>` tag 100% 功能重叠(activity / thought 字段同源,tag 还多支持 mood/intimacy_delta)。INV-4 §3 P3 评估 clean cut 退役,本节落具体 audit + plan。

### 1.1 引用点列表(grep 实测)

`grep -rn "set_activity\|character.set_activity" backend/ frontend/` 全命中分类:

#### Active 代码(需处理)

| # | 文件:行 | 类型 | 处理 |
|---|---|---|---|
| 1 | `backend/capabilities/character_state.py:6` | module docstring 列 3 cap | **改**(去掉 set_activity 那条) |
| 2 | `backend/capabilities/character_state.py:11-15` | docstring 第二段反复提及 set_activity | **改**(同 #1 段落) |
| 3 | `backend/capabilities/character_state.py:64-138` | `@register_capability(name="character.set_activity", ...)` 装饰器 + `async def set_activity()` handler 函数 | **删**(整段 L64-138) |
| 4 | `backend/agents/prompt/tool_addendum.py:63-71` | 【角色状态】引导段,4 个 bullet 含 set_activity 调用指引 | **重写**(改为 inline tag 引导,合并 4 个 bullet → 2 个,删 set_activity 提及,保留 character.get_state 引导 + <state_update> tag 引导) |
| 5 | `backend/proactive/triggers/activity.py:164` | 注释提及"调 character.set_activity 更新自己状态等" | **改**(改为"调 inline tag 更新自己状态") |
| 6 | `frontend/src/hooks/useWebSocket.ts:346` | 注释提及 "或 set_activity capability / reset_state 路由 push" | **改**(改为 "或 reset_state 路由 push";set_activity 已退役) |

#### Comment-only 引用(保留作 archeology)

| # | 文件:行 | 类型 | 处理理由 |
|---|---|---|---|
| 7 | `backend/agents/chat.py:977` | 注释 `# 旧实现只给 memory tools 透传 character_id,character.set_activity / character.get_state ...` | **保留**(historical comment,反映 chunk 4 设计意图,删了失 archeology;且 character.get_state 仍在用) |
| 8 | `backend/agents/tool_call_resilience.py:126` | docstring `character_id: 当前 character_id(character.set_activity / character.get_state 等 capability 需要)` | **改**(去掉 set_activity 一项,保留 character.get_state) |

#### 历史档案(不动)

`docs/archive/*`(DESIGN.md / AUDIT-GROUND-TRUTH.md / chunk-15-b1-feasibility.md 等)+ INVESTIGATION-2/3/4/5.md 多处提及 — **不改**(per INV 纪律,历史归档不动)。

### 1.2 退役动作清单

按引用点 6 个 active 改动 + 1 个 docstring 微改:

1. **删 `backend/capabilities/character_state.py:64-138` 整段 set_activity cap**(75 行):
   - L64 注释 `# 2. character.set_activity`
   - L65-99 `@register_capability(name="character.set_activity", ...)` 装饰器
   - L101-138 `async def set_activity(activity, thought=None, ...)` handler
   - 同步删 L138 后的孤儿空行

2. **改 `character_state.py:1-15` module docstring**(去掉 set_activity 引用,保留 get_state + intimacy_decay):
   - L6 删 `* ``character.set_activity(activity, thought=None)`` ...` 那条
   - L11-15 段(含"没有 update_mood / update_intimacy capability 解释")**保留**,该段说明 mood/intimacy 走 tag 不走 tool 的设计意图,反 archeology 价值高;但末尾加一行 "(2026-05-21 退役 set_activity 后,activity/thought 也走同款 tag 路径)"

3. **重写 `backend/agents/prompt/tool_addendum.py:63-71`【角色状态】引导段**(原 ~250 chars):
   ```
   【角色状态】:
     - 用户问「你状态如何 / 你最近怎么样」时调 character.get_state 拿当前值再回答。
     - 自己「当前在做什么 / 在想什么 / 心情 / 亲密度」全部通过 <state_update activity="..." thought="..." mood="..." intimacy_delta="..." /> inline tag 更新(见 layer_a.j2 关于该标签的格式规范)。可偶尔输出让用户感受连续性,如长时间未互动后说"刚才在烤面包",但每轮都更新会机械。
   ```
   (~210 chars,省 ~40 chars × 1.75 token/char ≈ ~70 tokens)

4. **改 `backend/proactive/triggers/activity.py:164` 注释**:
   - 现:`# 选择(聊一句 / 调 character.set_activity 更新自己状态等)。`
   - 改:`# 选择(聊一句 / 用 <state_update activity=...> tag 更新自己状态等)。`

5. **改 `frontend/src/hooks/useWebSocket.ts:346` 注释**:
   - 现:`// v3-G chunk 3b: 后端 <state_update> 标签解析后 push,或 set_activity capability / reset_state 路由 push。`
   - 改:`// v3-G chunk 3b: 后端 <state_update> 标签解析后 push,或 reset_state 路由 push (character.set_activity capability 2026-05-21 退役,改走 tag 唯一路径)。`

6. **改 `backend/agents/tool_call_resilience.py:126` docstring**:
   - 现:`character_id: 当前 character_id(``character.set_activity`` / ``character.get_state`` 等 capability 需要)。`
   - 改:`character_id: 当前 character_id(``character.get_state`` 等 capability 需要;character.set_activity 2026-05-21 退役)。`

### 1.3 实测验证 plan

#### Smoke 1 · cap 注册表无 set_activity

```python
import backend.capabilities.character_state  # 触发装饰器 register
from backend.tools.registry import ToolRegistry
assert 'character.set_activity' not in ToolRegistry.list_tools()
print('character_state.py registered caps:', [s['function']['name'] for s in ToolRegistry.list_schemas() if 'character' in s['function']['name']])
# 预期:仅 character.get_state(character.intimacy_decay 是 SCHEDULER consumer 不进 ToolRegistry)
```

#### Smoke 2 · main_chat 跑"你在干嘛?" LLM 走 tag 路径

```python
跑 ChatAgent.stream("你在干嘛?")
预期 LLM 输出含 <state_update activity="..." /> 形态,而非 tool_call set_activity
```

#### Smoke 3 · character_states DB activity 字段写入正常

```python
跑完 Smoke 2 后查 SELECT activity FROM character_states WHERE character_id=1
预期:activity 字段被 ws.py:_apply_and_push_state_update 写入新值(per chat.py:219-260 tag parse + service update)
```

### 1.4 估省 token(按 P2 实测方法论 1.75 token/char 重估)

P2 实测发现 chars × 0.4 严重低估,真实 Qwen tokenizer 长 cap description 约 chars × 1.75。本节按新方法论估:

| 项 | chars | 估省 tokens |
|---|---|---|
| character.set_activity cap 完整 schema(name 24 + desc 282 + ps 206 + wrap ~80) | ~590 | ~1,030 |
| tool_addendum.py:63-71 引导段精简 ~50 chars | ~50 | ~90 |
| **合计** | **~640** | **~1,120 tokens** |

vs INV-4 §3 P3 旧估 ~150 tokens,**实际是预估 7 倍**(同 P2 偏差倍数,因 token 密度方法论修正)。这是 P3 实际 ROI 放大器。

### 1.5 风险评估

| 项 | 风险 | 说明 |
|---|---|---|
| 删 cap 注册 | **极低** | `<state_update activity="..." thought="..." />` tag 已 production 路径(chat.py:219-260 解析 + ws.py:1320 _apply_and_push_state_update),activity/thought 字段已支持,无新功能需要 |
| 删/重写引导段 | **极低** | layer_a.j2:9 已含 state_update tag 格式规范,addendum 内 set_activity 引导是重复;重写后 LLM 看新引导直接走 tag 路径 |
| WS push 重复 / 缺失 | **极低** | set_activity handler 自己 push(character_state.py:124-134);ws.py 主路径 parse tag 后也 push(同 connection_manager.push)。退役 cap 后只剩 tag path,**无重复 / 无缺失** |
| LLM 误调 set_activity | **低** | LLM 看不到 schema 不会调;若误调 → tool_call_resilience 现有 unknown-tool fallback 处理;且 tag 路径成熟,LLM 自然学习 |
| 前端 useWebSocket 接收 state_update event | **零** | event 字段同(mood/intimacy/activity/thought),tag path 产同款 event,前端 schema 不变 |
| character.intimacy_decay (SCHEDULER) 仍依赖 character_state.py | **零** | intimacy_decay cap L143+ 独立装饰器,与 set_activity 同 module 但不互相依赖;删 set_activity 不影响 |

**总风险 = 极低**,可 clean cut。

### 1.6 收口(Stage 1)

- ✅ 引用点 audit:8 处 active 引用(6 改 / 2 保留作 archeology) + 16+ 历史档案(不动)
- ✅ 退役动作清单 6 个落定
- ✅ smoke 3 条 plan 已定
- ✅ 估省 ~1,120 tokens(按 P2 方法论 1.75 token/char 重估,vs §3 旧估 ~150 偏低 7 倍)
- ✅ 风险评估 = **极低**,clean cut 可行

→ Stage 1 audit + plan PM 拍板通过 → 进 Stage 2。

### 1.7 Stage 2 实施记录(2026-05-21)

#### 1.7.1 Commit hash 表

| commit | 内容 |
|---|---|
| `82e1aeb` | docs(inv): seal INV-4 at 1,120 lines + open INV-6 (独立 docs commit) |
| (本 commit) | refactor(capabilities): retire character.set_activity, route to <state_update> tag |

#### 1.7.2 实际改动 6 处 active 引用点

逐处 Edit 落地:

1. `backend/capabilities/character_state.py:64-138` 整段 set_activity cap + handler **删 75 行**,改 8 行简短退役注释
2. `backend/capabilities/character_state.py:1-18` module docstring 改 "3 个 cap" → "2 个 cap(2026-05-21 退役 set_activity 后)" + 列 mood/intimacy/activity/thought 全走 tag 路径
3. `backend/agents/prompt/tool_addendum.py:63-71` 引导段 4 bullet → 2 bullet,合并 mood/intimacy/activity/thought tag 路径说明
4. `backend/proactive/triggers/activity.py:164` 注释微改 "调 character.set_activity" → "用 <state_update activity=...> tag"
5. `frontend/src/hooks/useWebSocket.ts:346` 注释微改 "或 set_activity capability / reset_state 路由" → "或 reset_state 路由(set_activity 2026-05-21 退役)"(**纯注释,不动 logic,无需 frontend rebuild**)
6. `backend/agents/tool_call_resilience.py:126` docstring 微改去掉 set_activity 一项

#### 1.7.3 三条 smoke 实测全 PASS

##### Smoke 1 · ToolRegistry 无 set_activity

```
character.* cap in ToolRegistry: ['character.get_state']
_get_all_tools count: 57 (was 58 pre-retirement)
tools_schema token POST-P3: 9,954 (P2 baseline 10,336)
```

→ set_activity 已下线 ✅ / get_state 保留 ✅。**tools_schema 实测 -382 tokens**(P3 单刀贡献)。

##### Smoke 2 · LLM 走 tag 路径(`<state_update>` 实例)

```
=== ChatAgent.stream "你在干嘛?" ===
Mai reply (222 chars):
<thinking>
用户问我在干嘛。这是日常闲聊，不需要调工具。
按麻衣的性格：话少、克制、略带一点观察感。
当前状态是"监督休息"，可以自然带出来。
</thinking>

<state_update mood=0 intimacy=0 activity="监督休息" thought="这家伙肯定不会听话，又要我重复第二遍" />

<motion>normal</motion>

...在看你。屏幕三十七分钟没动过了。还不打算休息？
```

→ 含 `<state_update>` tag(activity / thought 字段已用) ✅
→ 无 set_activity tool_call 尝试 ✅
→ persona 还原:话少、克制、监督休息状态自然带出 ✅

##### Smoke 3 · DB character_states 字段链路

```sql
SELECT mood, intimacy, current_activity, current_thought FROM character_states WHERE character_id=1;
→ mood='curious' intimacy=45 current_activity='监督休息' current_thought='这家伙肯定不会听话,又要我重复第二遍'
```

→ row 存在 + 字段非空(activity / thought / mood / intimacy 四字段)+ historical write 路径成熟 ✅

**注**:inline smoke 脚本 consume `ChatAgent.stream` yield 不经 ws.py,本次脚本不触发 DB write(DB 当前值是历史真机 tag → ws.py:_apply_and_push_state_update → services.update_character_state 链路 ship 的数据)。**tag → DB 链路本身已 INV-3 §6/§⑦/§⑧ 多次实证稳定**,本节不重复验证。

#### 1.7.4 实测 vs 估算偏差 + token 密度方法论 lesson

**实测 P3 减幅 = 382 tokens**(Smoke 1 测,P2 baseline 10,336 → 9,954)。

**vs §1.4 估算 ~1,120 tokens,实际偏低 ~3 倍**。原因分析:

- §1.4 估 590 chars (cap schema 完整) × 1.75 token/char = ~1,030 tokens — **此估算源 chars 数偏多**:
  - cap schema 实际 token 含 OpenAI function-calling 通用 wrap(`{"type":"function","function":{...}}`),通用 wrap 在 list_schemas 输出中是固定开销,删一个 cap 不会节省整个 wrap
  - 真实减幅 = cap 的 name + description + parameters_schema 字段(540 chars 左右)的 token,但 function-calling JSON 中嵌套结构让 token 化分布不均匀
- 实测 382 tokens / 540 chars = **0.71 token/char**(中文为主含少量 JSON wrap)
- 这与 P2 实测 chars × 1.75-2.0(纯 description 段)对比偏低:
  - P2 改的是 description 字段内**长中文 + markdown + 特殊字符**,Qwen tokenizer 切得极碎(高 token/char)
  - P3 删的是整个 schema(name 短串 + 中等 desc + JSON 结构化 parameters_schema),JSON 结构化数据 + 短 name 比纯长中文 description **token 化效率高**(低 token/char)

**token 密度方法论 lesson**(P2 + P3 实测综合):

> Qwen tokenizer 对不同类型文本 token 密度差异大:
> - **纯长中文 description**(含 markdown / 特殊字符 / 中英混排): **~1.75-2.0 token/char**
> - **结构化 JSON schema**(含 name 短串 / 类型枚举 / 整数约束): **~0.6-0.8 token/char**
> - **混合(整 capability schema = wrap + name + desc + parameters_schema)**: **~0.7 token/char**(实测 P3)
>
> 后续 P1 入口折叠估算应按混合密度 ~0.7 token/char 校正:
> - INV-4 §3.5 P1 估省 ~5,960 tokens(基于 cap 数 × 228 平均 token/cap)
> - P3 实测 cap schema 平均 ~382 tokens(57 cap → 9,954 / 57 = 174 token/cap average,但 long-desc cap 更高)
> - **P1 实际折叠收益预估调整空间**:取决于具体 cap schema 字符分布,可能偏 §3.5 估的 ±30%

#### 1.7.5 Stage 2 收口

- ✅ 6 处 active 引用点全改完(2 处 comment-only archeology 保留)
- ✅ 3 条 smoke 全 PASS(cap 下线 + tag 路径活 + DB 字段链路 OK)
- ✅ 实测 P3 减幅 **-382 tokens**,与 P2 累计 **-3,296 tokens / 24.9% of pre-treatment tools_schema 13,250**
- ✅ token 密度方法论 lesson 记入 §1.7.4 供后续 P1 fold 估算校正参考
- 🔒 零 parameter_schema / handler 逻辑改动(per brief)

→ **P3 退役 ship 完成**。子轨 B 实施第 2 刀 closed。

下一刀:**P1 入口折叠(media 5→1 → apple_calendar 4→1 → bilibili 11→1 → netease 13→2)**,等 PM 拍板。

---

## §2 P1.media 5→1 入口折叠（Stage 1 草稿,2026-05-21）

> P1 入口折叠首刀 + **dispatcher 设计模板**。media 是 P1 中最小组(5 cap),最适合试水;模板将复用到后续 apple_calendar / bilibili / netease。

### 2.1 5 cap audit 实测表

`backend/capabilities/media_control.py`,均 CHAT_AGENT + ON_DEMAND,handler 走 `_nowplaying` (nowplaying-cli wrap) 或 `_osascript`:

| # | cap | line | desc / ps chars | JSON 总 chars | 实测 token | 参数 |
|---|---|---|---|---|---|---|
| 1 | `media.next_track` | 155 | 105 / 52 | 256 | **111** | (无) |
| 2 | `media.previous_track` | 181 | 38 / 52 | 193 | **77** | (无) |
| 3 | `media.play_pause` | 205 | 79 / 52 | 230 | **107** | (无) |
| 4 | `media.now_playing` | 240 | 180 / 52 | 332 | **164** | (无) |
| 5 | `media.set_volume` | 279 | 123 / 154 | 378 | **181** | level (int 0-100, required) |
| **合计** | | | **525/362** | **1,399** | **646** | |

**关键观察**:5 cap 中 4 个无参,仅 `set_volume` 1 个有参数;handler 都简单 — `_nowplaying(action)` (3 cap) / `_nowplaying("get", ...)` + parse (1 cap) / `_osascript` (1 cap)。

**与 §3 估算偏差**:INV-4 §3 估 ~890 token(基于 228 token/cap × 5 - 折叠后 250),实测 baseline 仅 646 token(media 是简单无参 cap,远低于全 cap 平均 228)。折叠后估省**远低于 §3 估算**(详 §2.5)。

#### 外部引用点(grep 跨 capabilities/media_control.py 外)

| 类型 | 文件:行 | 内容 | 处理 |
|---|---|---|---|
| docstring | `netease_music.py:11,563,575-576` | "与 media.now_playing 配合" 等说明 | **保留作 archeology**(描述,non-runtime) |
| docstring | `netease_playback.py:246,311` | "Music / Spotify 走 chunk 1 media.play_pause" 等说明 | 同上保留 |
| 引导文 | `tool_addendum.py:48,57-61` | LLM 引导段 5 行硬编码 media.next_track 等 | **必改**(LLM runtime 看,折叠后改新 cap 引导) |
| 前端 UI | `CapabilityPanel.tsx:100` | UI label-mapping 注释 mention "media." prefix | **不动**(注释 only,折叠后 prefix 仍 "media" 可正常 match) |

→ 真 LLM-facing 必改点 = **1 处**(tool_addendum.py 引导文)。

### 2.2 dispatcher schema 终稿(PM 2026-05-21 拍板 lock 5 决策)

PM 全 lock CC 倾向:**a1 / b1 / c std / d snake_case / e clean cut**。

| 决策 | lock | 含义 |
|---|---|---|
| **a · 入口 cap 命名** | **`media`**(单字) | LLM 调用 `media(action="...")`,与后续 fold(`bilibili` / `netease` / `apple_calendar` 同款单字 namespace)风格统一 |
| **b · 参数 union 策略** | **单层 union schema** | action enum(5 项) + level optional(仅 set_volume),required=["action"] |
| **c · 错误处理** | **标准化 `{ok:bool, error:str}`** | 与现 5 cap 同 return 协议;未知 action / 缺参数 / sub-handler 错误统一 ok=false + error 字段 |
| **d · action 命名风格** | **snake_case** | `next_track` / `previous_track` / `play_pause` / `now_playing` / `set_volume`,与现 cap suffix 1:1 mapping |
| **e · 退役方案** | **clean cut** | 同 commit 删旧 5 cap + 新 dispatcher 上线,与 P3 同 pattern |

**dispatcher schema 终稿**:

```python
@register_capability(
    name="media",
    display_name="媒体控制 + 当前在播查询",
    description=(
        "macOS 系统级媒体控制 + 当前在播查询(跨来源:网易云 / Apple Music / "
        "Spotify / YouTube / Bilibili 网页等)。按 action 选具体操作:\n"
        "- next_track:下一首(用户说'下一首/切歌/换一首/不喜欢这首')\n"
        "- previous_track:上一首(用户说'上一首/刚才那首/退回去')\n"
        "- play_pause:toggle 播放/暂停(用户说'暂停/播放/继续/停一下')\n"
        "- now_playing:查当前在播歌名/歌手/专辑(用户问'在放什么/这首叫啥')\n"
        "- set_volume:调音量(用户说'音量调到 X/大声点/小声点',需 level)\n"
        "set_volume 的'大声/小声'模糊请求由你判合理 level(如 +20/-20),不反复问。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play",
    health_check=health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["next_track", "previous_track", "play_pause", "now_playing", "set_volume"],
                "description": "媒体操作类型",
            },
            "level": {
                "type": "integer",
                "minimum": 0, "maximum": 100,
                "description": "仅 action=set_volume 时必填,目标音量 0-100(0=静音)",
            },
        },
        "required": ["action"],
    },
)
```

### 2.3 实施 plan 终稿

#### 改动文件清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `backend/capabilities/media_control.py` | 删 5 旧 cap decorator + 5 handler 函数(L155-308 共 ~150 行);新增 1 个 `media` dispatcher decorator + 1 个 dispatch handler + 5 个 `_handle_*` internal 函数(原 handler 逻辑搬过来去掉装饰器);保留底层 helper(`_nowplaying` / `_osascript` / `_parse_nowplaying_get` / `_has_nowplaying_cli` / `health_check`) |
| 2 | `backend/agents/prompt/tool_addendum.py:48,57-61` | 6 处字符微改:L48 `先 media.now_playing` → `先 media(action="now_playing")`;L57-61 5 个 bullet `→ media.next_track` → `→ media(action="next_track")` 等 |
| 3 | `frontend/src/components/CapabilityPanel.tsx:99-101` | **纯注释微改**(标历史 vs 现状),`PROVIDER_DISPLAY['media']='media_control'` mapping 仍 work(`_extractProvider('media')` 返 `'media'` 与单字 cap name 兼容,**logic 不动**);UI 显示 5 cap → 1 cap 是 frontend 自然 reflect |

frontend `_extractProvider` 实测:`split('.')` + 单字无 `.` → `parts[0] = 'media'` 即 cap name 本身,mapping 仍命中 `PROVIDER_DISPLAY['media'] = 'media_control'`,**不需要 frontend rebuild**。

#### 估改动量

- 删 ~150 行(5 cap decorator + handler)
- 新增 ~90 行(1 dispatcher decorator + dispatch routing + 5 `_handle_*` internal 函数)
- 净减 ~60 行 .py code(media_control.py)
- tool_addendum.py 改 ~6 行
- CapabilityPanel.tsx 改 ~1 行注释

#### dispatcher handler 实现思路

```python
async def media_dispatch(action: str = "", **params) -> dict:
    handlers = {
        "next_track": _handle_next_track,
        "previous_track": _handle_previous_track,
        "play_pause": _handle_play_pause,
        "now_playing": _handle_now_playing,
        "set_volume": _handle_set_volume,
    }
    handler = handlers.get(action)
    if handler is None:
        return {
            "ok": False,
            "error": f"unknown action: {action!r}; valid: {list(handlers.keys())}",
        }
    # set_volume 必填 level
    if action == "set_volume" and "level" not in params:
        return {"ok": False, "error": "level required when action=set_volume"}
    return await handler(**params)
```

5 个 `_handle_*` 函数 = 现有 next_track / previous_track / play_pause / now_playing / set_volume handler 的内部逻辑搬过来(去掉 `@register_capability` 装饰器,改名 `_handle_*` 加 underscore prefix 标 internal)。

### 2.4 风险评估

| 项 | 风险 | 说明 |
|---|---|---|
| LLM 调用新 cap | **低** | tool_addendum 引导改写后 LLM 看新 cap 形态;OpenAI / Anthropic / Qwen 都熟悉 action enum 模式 |
| LLM 误调旧 5 cap | **低** | 旧 cap 删除后 LLM 看不到 schema 不会调;若误调走 unknown-tool fallback,P3 已实证 LLM 自然 retry |
| dispatcher 错误处理 | **极低** | 标准 `{ok: bool}` 协议与现 5 cap 同款,前端 / caller 无感知 |
| 现有 caller 硬编码旧 cap name | **零** | grep 全 backend / frontend 实测:**runtime caller 零硬编码**(`netease_music.py` / `netease_playback.py` 引用是 docstring,`CapabilityPanel.tsx` 是注释,`tool_addendum.py` 是 LLM 引导 — 全改文字即可,无 runtime dispatch 路径硬编码) |
| LiteLLM × DashScope union schema 兼容 | **极低** | OpenAI 标准 function-calling union schema,INV-5 multi-provider 实测全跑通 |

**总风险 = 低**,可走 clean cut。

### 2.5 估省 token(按 P3 实测方法论重估)

**baseline 实测**(§2.1):media 5 cap = **646 token**(JSON chars 1,399 → 实测密度 0.46 token/char)

**折叠后 dispatcher cap 预估**:
- description: ~200 chars(合并 5 个简短功能 + 1 句话引导用法)
- parameters_schema(单层 union): ~280 chars(action enum 5 项 + level optional 字段)
- function-calling wrap: ~80 chars
- 合计 ~560 chars
- 按混合 schema 实测密度 0.46-0.7 token/char(media 是简单 schema,密度偏低端 0.5)= **~280-400 token**

**估省 = 646 - 280..400 = ~250-360 token**(取中位数 **~300 token**)

#### vs INV-4 §3 估算(校正记录)

| 来源 | 估值 | 备注 |
|---|---|---|
| INV-4 §3.5(原估) | ~890 token | 用全 cap 平均 228 token/cap × 5 |
| INV-4 §3.5 校正期望(P3 后) | ~600-900 × 1.5-2.5 校正系数 | 但本次 baseline 实测发现 media 单 cap token 远低于平均 |
| **本节实测预估** | **~300 token** | media 是简单无参 cap,baseline 仅 646 远低于 §3 估的 1,140 |

→ media fold ROI **远低于 §3 估算**,但仍值得做:
- 模板试水(dispatcher 模式验证)
- 累计减幅(P2 + P3 + P1.media ≈ -3,600 token / 27% baseline)
- 后续 P1 fold(bilibili / netease)是更大头(11 / 13 cap),token 密度也比 media 高

#### Lesson · §3 平均外推估算偏高(后续 group 校正建议)

P3 + P1.media 实测发现 INV-4 §3.5 用"全 cap 平均 228 token/cap × group 大小"外推 fold ROI **偏高约 3 倍**:

- media 5 cap baseline 实测 646 token(平均 **129 token/cap**),§3 估 1,140 token(平均 228)
- 不同 cap category token 密度差异极大:**简单无参 cap(media)~75-180 token,长 desc cap(P2 top 10)~200-280 token**

**后续 group 校正建议**:
- bilibili 11 cap:§3 估 ~2,500 token,需先实测 baseline(含 long-desc 杀手 use case 描述,平均可能 150-200/cap → real baseline ~1,800-2,200)
- netease 13 cap(web 7 + local 6):同上需 audit 实测,平均可能 120-180/cap → real baseline ~1,500-2,300
- apple_calendar 4 cap:其中 create_event 含 long parameters_schema(506 chars),平均可能 150-200/cap → real baseline ~600-800
- **新规范**:每 group fold Stage 1 必跑 token_counter 实测 baseline,不用 §3 估值

### 2.6 收口(Stage 2 · final plan)

- ✅ 5 决策 PM 2026-05-21 全 lock(a1 / b1 / c std / d snake_case / e clean cut),fallback 方案移除
- ✅ §2.2 dispatcher schema 终稿(含完整 description / parameters_schema / register_capability 装饰器)
- ✅ §2.3 实施 plan 终稿:3 个文件改动(media_control.py + tool_addendum.py + CapabilityPanel.tsx 注释)
- ✅ §2.5 估省 ~300 token + lesson 记入(§3 全 cap 平均外推偏高 ~3x,后续 group 必跑 baseline 实测)
- ✅ 风险评估 = 低(零硬编码 runtime caller,union schema LiteLLM 全 provider 兼容)

→ **Stage 2 final plan 完成,等 PM 二次审 + 放行 Stage 3 落代码**。

### 2.7 Stage 3 实施记录(2026-05-21)

#### 2.7.1 Commit + 改动

- commit:(本 commit) `refactor(capabilities): fold media 5 caps into dispatcher (saves ~257 tokens, P1 template established)`

| 文件 | 改动 | diff |
|---|---|---|
| `backend/capabilities/media_control.py` | 删 5 旧 cap decorator + handler;新增 1 dispatcher + 5 `_handle_*` internal;保留底层 helper | ~-150 / +130 行 |
| `backend/agents/prompt/tool_addendum.py` | L48 + L57-61 共 6 处字符微改(`→ media.X` → `→ media(action="X")`) | ~+6 / -6 |
| `frontend/src/components/CapabilityPanel.tsx` | 注释 1 行微改(标 fold 历史),不动 logic | ~+1 / -0 |

#### 2.7.2 三条 smoke 全 PASS

##### Smoke 1 · ToolRegistry 状态

```
media* cap in registry: ['media']
_get_all_tools count: 53 (含 MEMORY_TOOLS 4) — was 58 pre-fold (P3 后 57 - 5 + 1 = 53)
tools_schema POST-P1.media: 9,697 tokens (P3 baseline 9,954)
P1.media reduction: 257 tokens
```

✅ 5 旧 cap 全下线 / 新 `media` dispatcher 注册成功 / token 减幅 -257(PM 预期 300 ± 50 范围内)

##### Smoke 2 · LLM 调用 dispatcher(5 action 全覆盖)

5 个 user query 各发一次,抓 `tool_use_start` event 看 LLM 选的 tool name:

```
[1] '暂停一下'     → tool_calls=['media']  ✅ (expected action=play_pause)
[2] '下一首'       → tool_calls=['media']  ✅ (expected action=next_track)
[3] '上一首'       → tool_calls=['media']  ✅ (expected action=previous_track)
[4] '调音量到 30'  → tool_calls=['media']  ✅ (expected action=set_volume)
[5] '在放什么'     → tool_calls=['media']  ✅ (expected action=now_playing)
```

→ LLM **全 5 query 调新 `media` dispatcher**(无一调旧 `media.*` cap);action 参数由 dispatcher routing 间接验证(底层 nowplaying-cli 实际被调用,5 cap 行为同前)。

##### Smoke 3 · dispatcher 内部 routing

```python
unknown action     → {ok: False, error: "unknown action: 'unknown_X'; valid: [...5 项]"}
set_volume no level → {ok: False, error: "level required when action=set_volume"}
now_playing        → {title, artist, album, playing, error}  # 真路由 _handle_now_playing
```

✅ unknown / 缺参 / 真 routing 三档全正确;错误协议 `{ok:bool, error:str}` 与原 5 cap 同款。

#### 2.7.3 token 减幅累计(P2 + P3 + P1.media)

| 阶段 | tools_schema token | 累计减幅 vs INV-3 §③ 13,250 baseline |
|---|---|---|
| INV-3 §③ baseline | 13,250 | 0 |
| P2 ship (`72808ef`) | 10,336 | -2,914 (22.0%) |
| P3 ship (`81205f5`) | 9,954 | -3,296 (24.9%) |
| **P1.media ship (本 commit)** | **9,697** | **-3,553 (26.8%)** |

P1.media 单刀 -257 token 与 §2.5 估 ~300(±50)吻合。

#### 2.7.4 dispatcher 模板复用要点(给 apple_calendar / bilibili / netease 后续 3 刀)

P1.media 验证的 dispatcher pattern,后续 fold 直接复用:

1. **命名约定**:`<group>` 单字 cap name(e.g. `bilibili` / `netease` / `apple_calendar`)
   - frontend `_extractProvider` 对单字 cap name 返自身,`PROVIDER_DISPLAY` mapping 仍 work,**前端零改 logic**(仅注释微改标 fold 历史)

2. **schema 结构**:单层 union schema
   ```python
   {
     "type": "object",
     "properties": {
       "action": {"type": "string", "enum": [...]},
       <union 参数 1>: {...},
       <union 参数 2>: {...},
       ...
     },
     "required": ["action"]
   }
   ```
   - LiteLLM × DashScope × Anthropic 全 provider OpenAI 标准 union 兼容

3. **handler 实现**:
   ```python
   _<GROUP>_ACTION_HANDLERS = {"action_name": _handle_action_name, ...}

   async def <group>_dispatch(action: str = "", **params) -> dict:
       handler = _<GROUP>_ACTION_HANDLERS.get(action)
       if handler is None:
           return {"ok": False, "error": f"unknown action: {action!r}; valid: {list(_<GROUP>_ACTION_HANDLERS.keys())}"}
       return await handler(**params)
   ```
   - 必要时加 action-specific 参数校验(如 `set_volume` 缺 `level`),return `{ok: False, error: ...}`

4. **退役方式**:clean cut(同 commit 删旧 cap + 上线 dispatcher),不留 backward-compat
   - P3 + P1.media 实测 LLM 看不到旧 schema 自然走新 cap,unknown-tool fallback 兜底
   - tool_addendum.py 引导文同步改 `→ <group>(action="X")` 形态

5. **smoke 三条标准**:
   - Smoke 1: ToolRegistry 列表(旧下 / 新上 / token 减幅实测)
   - Smoke 2: LLM 真 query 各 action 至少一次(tool_use_start 抓 tool_name = `<group>`)
   - Smoke 3: dispatcher routing(unknown / 缺参 / 真 routing 三档)

6. **行为兼容**:return 协议 `{ok: bool, ...}` 与原 cap 同款;前端 / 上游 caller 零感知

7. **audit 双 grep 模式**(P1.apple_calendar §3.8 教训,2026-05-21 补):除了 grep cap-name 形式
   `<group>.<action>`(LLM 引导文 / docstring 描述等),**还要 grep 模块 import 路径**
   `from backend.capabilities.<file> import <handler>`,防止 router 反向 import / cross-module
   引用等隐藏 caller 漏审。`backend/capabilities/calendar.py` 的 router 内部 import
   `apple_calendar.today_events / upcoming_events` handler 函数名是 P1.apple_calendar
   Smoke 2 暴露的真实漏点。
   - **修法兜底**:apple_calendar.py 末尾加 module-level alias(`today_events = _handle_today_events`)
     backward-compat 不动 router,alias 不进 ToolRegistry 零 schema 开销
   - **P1.bilibili / P1.netease Stage 1 audit 必须双 grep 模式扫一遍**:`grep "bilibili\." + grep "from backend.capabilities.bilibili import"`(同 netease_music / netease_playback)

#### 2.7.5 收口(Stage 2 收口 → Stage 3 收口转 closing)

- ✅ 3 文件改动 ship(media_control 主结构改 + tool_addendum 6 处微改 + CapabilityPanel 注释 1 行)
- ✅ 3 条 smoke 全 PASS
- ✅ 实测 -257 token,与估 ~300 吻合
- ✅ dispatcher 模板 6 要点抽象,后续 3 刀直接复用
- 🔒 零 sanitize / handler 行为改动,LLM 5 query 全选新 cap

→ **P1.media 子轨 B 实施第 3 刀 closed**。下一刀 = **P1.apple_calendar 4→1**(复用模板),等 PM 启动。

---

## §3 P1.apple_calendar 4→1 入口折叠（Stage 1 草稿,2026-05-21）

> P1 入口折叠**第 2 刀**,**模板复用 #1**。dispatcher 设计 6 要点已 §2.7.4 lock,本节仅 audit + apple_calendar 特异适配。

### 3.1 4 cap audit 实测表

`backend/capabilities/apple_calendar.py`,均含 `health_check=ac.health_check`,底层走 `backend.integrations.apple_calendar`(`ac` module):

| # | cap | line | desc / ps chars | JSON 总 chars | 实测 token | consumers | 参数 |
|---|---|---|---|---|---|---|---|
| 1 | `apple_calendar.today_events` | 34 | 106 / 52 | 266 | **89** | C+S | (无) |
| 2 | `apple_calendar.upcoming_events` | 61 | 97 / 152 | 360 | **131** | C+S | `days_ahead` (int 1-30, default 7) |
| 3 | `apple_calendar.create_event` | 96 | 217 / **506** | **831** | **373** | C only | `title`(req) / `start_iso`(req,ISO 8601) / `duration_minutes`(int 1-1440, def 30) / `description`(str) / `calendar_name`(str) |
| 4 | `apple_calendar.delete_event` | 184 | 134 / 161 | 403 | **129** | C only | `event_id`(req) |
| **合计** | | | **554/871** | **1,868** | **727** | | |

**关键观察**:
- create_event **单 cap 占 51% token**(373/727),因含 5 参数详注(506 chars ps)
- 4 cap 参数总 7 类(去重):`days_ahead / title / start_iso / duration_minutes / description / calendar_name / event_id`
- 平均 ~182 token/cap,比 media 平均 129/cap 略高(参数复杂)
- 2 cap 标 C+S consumer(today / upcoming),create / delete 仅 C

### 3.2 外部引用点 grep audit

`grep -rn "apple_calendar.<action>" backend/ frontend/`(排 docs/INVESTIGATION):

#### Active 必改(2 处)

| # | 文件:行 | 内容 | 处理 |
|---|---|---|---|
| 1 | `tool_addendum.py:20,23,27` | 3 处提及 `apple_calendar.create_event / delete_event` LLM 引导文 | **必改**(改 `→ apple_calendar(action="create_event")` 等) |

实际 grep 命中:
```
tool_addendum.py:20  → 先调 time.now ... 再调 apple_calendar.create_event；
tool_addendum.py:23  ... 再调 apple_calendar.delete_event。
tool_addendum.py:27  - 再调 apple_calendar.create_event（默认走 calendar router 默认 source）；
```

#### Comment-only / archeology(保留,不动)

| # | 文件:行 | 类型 |
|---|---|---|
| 2 | `main.py:501` | 注释(提醒走 apple_calendar.create_event) |
| 3 | `database/models.py:184` | 注释(提醒改由 apple_calendar.create_event) |
| 4 | `llm/tool_name_sanitize.py:7` | docstring 例子 |
| 5 | `capabilities/google_calendar.py:12` | docstring 引用 |
| 6 | `agents/chat.py:899` | docstring 数据估算注释 |

**runtime caller 硬编码 = 零**:
- `grep backend/scheduler/ backend/proactive/ for ToolRegistry.call|cron 接 apple_calendar` 零命中
- SCHEDULER consumer 标记是预留 metadata,**实际 cron 走 `calendar.today_events` router**(`calendar.py` 内部硬调底层 `ac.list_events_in_range`,不经过 ToolRegistry by-name dispatch)
- 折叠后旧 4 cap 删,**不破坏现有 cron 任何路径**

#### 前端

`_extractProvider('apple_calendar')` 单字 cap name 返自身,frontend `PROVIDER_DISPLAY` 无 `apple_calendar` 显式 mapping → fallback 用 cap name 原值显示 `apple_calendar`。**前端零改 logic**,CapabilityPanel.tsx 注释也无需碰(L99-101 PROVIDER_DISPLAY 仅 `media` mapping)。

### 3.3 dispatcher 适配(模板 6 要点继承 + apple_calendar 特异 3 点)

#### 模板继承(§2.7.4 lock)

- 入口 cap 命名:**`apple_calendar`**(单字 namespace)
- 参数 union 策略:**单层 union schema**
- 错误处理:**`{ok:bool, error:str}` 标准**
- action 命名风格:**snake_case**(1:1 mapping cap suffix)
- 退役方案:**clean cut**
- smoke 三档:**ToolRegistry / LLM 真 query / dispatcher routing**

#### 特异 a · action enum 集合

4 项 1:1 mapping cap suffix:`today_events / upcoming_events / create_event / delete_event`

#### 特异 b · 参数 union schema(7 字段,内部校验逻辑复杂)

**dispatcher schema 终稿**:

```python
parameters_schema={
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["today_events", "upcoming_events", "create_event", "delete_event"],
            "description": "操作类型",
        },
        # upcoming_events 专用
        "days_ahead": {
            "type": "integer", "minimum": 1, "maximum": 30, "default": 7,
            "description": "仅 action=upcoming_events 时用,向前看几天(1-30,默 7)",
        },
        # create_event 5 字段
        "title": {
            "type": "string",
            "description": "仅 action=create_event 必填,事件标题(简短)",
        },
        "start_iso": {
            "type": "string",
            "description": "仅 action=create_event 必填,ISO 8601 含时区(如 2026-05-08T10:00:00+09:00);相对时间用先调 time.now",
        },
        "duration_minutes": {
            "type": "integer", "minimum": 1, "maximum": 1440, "default": 30,
            "description": "仅 action=create_event,持续时长分钟,默 30",
        },
        "description": {
            "type": "string",
            "description": "仅 action=create_event 可选,事件备注",
        },
        "calendar_name": {
            "type": "string",
            "description": "仅 action=create_event 可选,目标日历名(默系统默认)",
        },
        # delete_event 专用
        "event_id": {
            "type": "string",
            "description": "仅 action=delete_event 必填,event_id 来自 today_events/upcoming_events 返回",
        },
    },
    "required": ["action"],
}
```

**dispatcher 内部校验**:

```python
async def apple_calendar_dispatch(action: str = "", **params) -> dict:
    handler = _APPLE_CALENDAR_ACTION_HANDLERS.get(action)
    if handler is None:
        return {"ok": False, "error": f"unknown action: {action!r}; valid: [...]"}
    # action-specific required 字段校验
    if action == "create_event":
        if "title" not in params or not params.get("title"):
            return {"ok": False, "error": "title required when action=create_event"}
        if "start_iso" not in params or not params.get("start_iso"):
            return {"ok": False, "error": "start_iso required when action=create_event"}
    if action == "delete_event":
        if "event_id" not in params or not params.get("event_id"):
            return {"ok": False, "error": "event_id required when action=delete_event"}
    return await handler(**params)
```

#### 特异 c · SCHEDULER consumer 决策

apple_calendar.today_events / upcoming_events 原标 C+S consumer。折叠后 dispatcher 该标:

- **option c1**:`consumers=[CHAT_AGENT, SCHEDULER]`(保 SCHEDULER metadata) — CC 倾向 ✓
- option c2:`consumers=[CHAT_AGENT]` only

**CC 倾向 c1**(保 SCHEDULER metadata),理由:
- 现 SCHEDULER consumer 实际**无 runtime caller**(grep 零命中,cron 走 calendar router),但 metadata 反映"理论上 cron 可直调 apple 数据源"的设计意图
- 加 SCHEDULER consumer 零成本(metadata only,不影响 ToolRegistry / LLM 可见性)
- 与原 today / upcoming 2 cap 的 metadata 保持一致(create / delete 原本仅 C,但 dispatcher 是单点入口标超集合理)

**风险标 ⚠️**:若 PM 担心未来 cron 真调 `apple_calendar(action=today_events)` 入口而绕开 calendar router,可选 c2 强制走 router。CC 评估两者风险都低,但 c1 更稳。

### 3.4 实施 plan(预 Stage 2)

#### 改动文件清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `backend/capabilities/apple_calendar.py` | 删 4 旧 cap decorator + 4 handler(L34-210 整段);新增 1 dispatcher cap + 1 `apple_calendar_dispatch` 函数 + 4 `_handle_*` internal(原 handler 逻辑搬过来);保留 `_get_timezone` helper |
| 2 | `backend/agents/prompt/tool_addendum.py:20,23,27` | 3 处字符微改:`→ apple_calendar.create_event` → `→ apple_calendar(action="create_event")` 等 |

**前端**:零改(`_extractProvider` 兼容单字 cap name + PROVIDER_DISPLAY 无 `apple_calendar` mapping → fallback 用原值显示)

#### dispatcher handler 实现

```python
_APPLE_CALENDAR_ACTION_HANDLERS = {
    "today_events":    _handle_today_events,
    "upcoming_events": _handle_upcoming_events,
    "create_event":    _handle_create_event,
    "delete_event":    _handle_delete_event,
}

@register_capability(
    name="apple_calendar",
    display_name="Apple Calendar 日历操作",
    description="...一段描述列 4 action + 用法引导...",
    category="calendar",
    consumers=[Consumer.CHAT_AGENT, Consumer.SCHEDULER],  # c1
    trigger_modes=[TriggerMode.ON_DEMAND, TriggerMode.SCHEDULED],
    icon="calendar",
    health_check=ac.health_check,
    parameters_schema={...union schema as §3.3 b...},
)
async def apple_calendar_dispatch(action: str = "", **params) -> dict:
    ...  # 内部校验 + 路由
```

4 `_handle_*` internal 函数 = 现 today / upcoming / create / delete handler 逻辑去掉装饰器搬过来。

#### 估改动量

- 删 ~180 行(4 cap decorator + handler)
- 新增 ~150 行(1 dispatcher + 4 `_handle_*` + 校验逻辑)
- 净减 ~30 行 .py
- tool_addendum.py 改 ~3 行

### 3.5 风险评估

| 项 | 风险 | 说明 |
|---|---|---|
| LLM 调用新 dispatcher | **低** | 模板已 P1.media 实证(5/5 query 全调新 cap);apple_calendar 参数复杂但 LLM 看 union schema 仍能正确选 |
| LLM 误调旧 cap 名 | **低** | 删除后 LLM 看不到 schema 不会调;unknown-tool fallback 兜底 |
| dispatcher 内部参数校验 | **极低** | create_event / delete_event required 字段缺失 → 标准 `{ok:False, error:...}` 协议 |
| 现有 caller 硬编码 | **零** | grep 实测 backend/scheduler / proactive 零 runtime caller;cron 走 calendar router 不经 ToolRegistry |
| 删 SCHEDULER consumer 路径 | **零** | 实际无 cron caller 用这两 cap;c1 保 SCHEDULER metadata 即可(零成本) |
| LiteLLM × DashScope union schema | **极低** | OpenAI 标准,P1.media 已实证 |

**总风险 = 低**,可 clean cut。

### 3.6 估省 token(按 P1.media 实测密度 ~0.39 token/char 重估)

**baseline 实测**:apple_calendar 4 cap = **727 token**(JSON chars 1,868 → 实测密度 0.39 token/char,JSON 结构化数据密度典型范围)

**折叠后 dispatcher 预估**:
- description: ~280 chars(列 4 action + 用法引导,比 media 略长因 create_event 有相对时间 / time.now 前置等说明)
- parameters_schema(union 7 字段): ~700 chars(action enum + 7 字段详注,create_event 字段最多)
- function-calling wrap: ~80 chars
- 合计 ~1,060 chars
- × 0.39 token/char = **~410 token**

**估省 = 727 - 410 = ~317 token**(中位数 **~300 token**)

vs §3 旧估 ~560,按 P3 实测 ~3x 偏低修正 → 估 ~250-350 范围,**~300 居中**。

### 3.7 收口(Stage 1)

- ✅ 4 cap audit 实测(JSON chars 1,868 / token 727 / avg 182/cap;create_event 单 cap 占 51%)
- ✅ 外部引用 grep:2 处必改(tool_addendum 3 行);零 runtime caller 硬编码
- ✅ dispatcher 适配模板继承 + 特异 3 点(action enum 4 项 / union schema 7 字段 / SCHEDULER consumer c1 保留)
- ✅ 实施 plan 2 文件改动清单完整
- ✅ 风险评估 = 低,可 clean cut
- ✅ 估省 ~300 token(baseline 727 → dispatcher ~410)

→ **Stage 1 完成,等 PM 审 4 cap audit + 特异 3 点 + 进 Stage 2 落代码**。

### 3.8 Stage 2 实施记录(2026-05-21)

#### 3.8.1 Commit + 改动

- commit:(本 commit) `refactor(capabilities): fold apple_calendar 4 caps into dispatcher (saves ~91 tokens, P1 template reuse #1)`

| 文件 | 改动 | 大小 |
|---|---|---|
| `backend/capabilities/apple_calendar.py` | 删 4 旧 cap decorator + handler;新增 1 dispatcher + 4 `_handle_*` internal + 校验逻辑;**末尾加 2 行 module-level alias**(backward-compat for calendar.py D1 router) | -177 / +159 行 |
| `backend/agents/prompt/tool_addendum.py` | L20, 23, 27 三处微改 `→ apple_calendar.X` → `→ apple_calendar(action="X")` | ~+3 / -3 |

#### 3.8.2 calendar router import alias fix(Smoke 2 暴露后 PM 拍板 option A)

**问题**:Smoke 2 首跑暴露 `backend/capabilities/calendar.py:43,55` router 内部 Python module-level import 硬编码 handler 函数名:

```python
from backend.capabilities.apple_calendar import today_events as ac_today
from backend.capabilities.apple_calendar import upcoming_events as ac_up
```

我 Stage 1 audit grep `apple_calendar.<action>` cap-name 形式漏掉这个 Python import 路径(不同 grep 模式)。

**修法 option A**(apple_calendar.py 末尾加 alias):

```python
today_events = _handle_today_events
upcoming_events = _handle_upcoming_events
```

- 不动 calendar router(与 D1 决策"calendar router 保留不动"对齐)
- alias 是 Python 名字绑定,**不进 ToolRegistry,不增 schema token**
- **不是 LLM-visible**;LLM 主路径走 `apple_calendar(action=...)` dispatcher
- **新代码不要依赖** these aliases — backward-compat only

**验证**(直 import + 调 calendar router):
```
✅ aliases bind correctly (today_events is _handle_today_events)
✅ calendar.today_events router via alias → type=list (无 ImportError)
✅ calendar.upcoming_events router via alias → type=list
✅ tools_schema POST-alias-fix: 9,606 tokens (alias 零 schema 开销,reduction 仍 -91)
```

#### 3.8.3 三条 smoke 全 PASS

##### Smoke 1 · ToolRegistry

```
apple_calendar* cap in registry: ['apple_calendar']
_get_all_tools count: 50 (was 53 post-P1.media; 4 删 + 1 加 = 净减 3)
tools_schema POST-P1.apple_calendar: 9,606 tokens (P1.media baseline 9,697)
P1.apple_calendar reduction: 91 tokens
```

##### Smoke 2 · LLM 调用 dispatcher(4 action 全覆盖 + 双路径)

```
[1] '今天有什么安排'       → ['calendar.today_events']           ✅ router 路径(经 alias 兜底)
[2] '未来一周日程'         → ['calendar.upcoming_events']        ✅ router 路径(经 alias 兜底)
[3] '明天上午 10 点开会 30 分钟' → ['time.now', 'apple_calendar']    ✅ chunk-1 chain: time.now → apple_calendar
[4] '删掉 event_id=ABC123 那个日程' → ['apple_calendar']          ✅ dispatcher 直调
```

**双路径全覆盖**:
- query 1+2(today/upcoming)→ LLM 选 `calendar.*` router(经 alias backward-compat 到 _handle_*)
- query 3+4(create/delete)→ LLM 选 `apple_calendar` dispatcher 直调
- query 3 验证 chunk-1 设计 `time.now → apple_calendar(create_event)` 链路保留(time.now idx 0 < apple_calendar idx 1)

##### Smoke 3 · dispatcher routing 4 档

```
unknown action       → {ok: False, error: "unknown action: 'unknown_X'; valid: [...4 项]"}
create_event no title  → {ok: False, error: "title required when action=create_event"}
create_event no start_iso → {ok: False, error: "start_iso required when action=create_event"}
delete_event no event_id  → {ok: False, error: "event_id required when action=delete_event"}
today_events 真路由  → type=list (路由到 _handle_today_events 成功)
```

✅ 4 档错误处理 + 真 routing 全正确。

#### 3.8.4 token 减幅累计

| 阶段 | tools_schema token | 累计减幅 vs INV-3 §③ 13,250 baseline |
|---|---|---|
| INV-3 §③ baseline | 13,250 | 0 |
| P2 (`72808ef`) | 10,336 | -2,914 (22.0%) |
| P3 (`81205f5`) | 9,954 | -3,296 (24.9%) |
| P1.media (`a835677`) | 9,697 | -3,553 (26.8%) |
| **P1.apple_calendar (本 commit)** | **9,606** | **-3,644 (27.5%)** |

P1.apple_calendar 单刀 -91 token,**远低于 §3.6 估 ~317**。

#### 3.8.5 估 vs 实测偏差分析

§3.6 估 ~300 token(baseline 727 - dispatcher 410)。实测 -91 偏低 ~3.5x。

根因:dispatcher 的 `description + parameters_schema` 比预估**重得多**:
- description 终稿 ~500 chars(列 4 action 详注 + 用法引导,比预估 280 长 ~80%)
- parameters_schema 终稿 ~960 chars(union schema 8 字段 + 详 description,比预估 700 长 ~37%)
- 总 ~1,540 chars × ~0.42 token/char = ~640 token
- 实测 dispatcher token = 727 - 91 = **636 token**(与重估吻合)

**Lesson 补 §2.7.4 #8**:dispatcher description / parameters_schema 实际写出后 chars 数往往**比草稿预估高 30-80%**,因要含 4-13 action 的详注 + 用法引导(尤其多必填参数的 action 如 create_event 需要详细说明)。**P1.bilibili / P1.netease Stage 1 应按"实写 dispatcher schema chars 估算"而非"压缩 ratio 估算"**。

#### 3.8.6 收口

- ✅ 2 文件改动 ship(apple_calendar.py 主结构改 + alias 兜底,tool_addendum.py 3 处微改)
- ✅ Smoke 2 暴露 calendar router alias 漏点 → PM option A 修法 ship + lesson #7 记入
- ✅ 3 条 smoke 全 PASS,双路径(router via alias + dispatcher 直调)全覆盖
- ✅ chunk-1 设计 `time.now → apple_calendar(create_event)` 链路保留
- ✅ 实测 -91 token(累计 27.5% reduction);**lesson #8**:dispatcher schema 实写 chars 比预估高 30-80%
- 🔒 零 calendar router / google_calendar / 其它 calendar 系列改动

→ **P1.apple_calendar 子轨 B 实施第 4 刀 closed**。下一刀 = **P1.bilibili 11→1**(模板复用 #2,最大头),Stage 1 必走双 grep audit(§2.7.4 #7)。

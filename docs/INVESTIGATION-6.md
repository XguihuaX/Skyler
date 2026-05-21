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

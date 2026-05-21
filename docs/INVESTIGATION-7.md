# Investigation 7 · 子轨 B 工具治理实施收尾（P1.bilibili + P1.netease）

> 接 INV-6 915 行封存（2026-05-21）。
> 模板 reference:
>   - INV-6 §2.7.4 dispatcher 6 要点(命名 / union schema / handler 实现 / 退役方式 / smoke 三档 / 行为兼容)
>   - **lesson #7** 双 grep audit(cap-name pattern + Python module import pattern)— 继承 INV-6 §3.8
>   - **lesson #8** dispatcher 实写 chars 比预估高 30-80%(后续 group 按实写估算)— 继承 INV-6 §3.8
>   - **lesson #9** frontend `startsWith` 模式与 cap-name grep / module import grep 都不同,fold 单字 namespace 后 prefix 失 mapping → UX 降级 — 本 INV §1.7 新增(2026-05-21 P1.bilibili Stage 2 暴露 + retro-fix)
> 期望管理: 按 lesson #8 校正,剩余两刀实际 saving 可能 -1,300 到 -3,200 token(vs §3 原估 -4,510),仍显著但低于乐观估计。

## §1 P1.bilibili 11→1 入口折叠 (Stage 1 audit + 适配 plan, 2026-05-21)

> P1 入口折叠**第 3 刀**,**模板复用 #2**,**最大头**(11 cap)。模板 6 要点 + lesson #7-8 全继承。

### 1.1 11 cap audit 实测表

`backend/capabilities/bilibili.py`,全 CHAT_AGENT + ON_DEMAND,底层走 `backend.integrations.bilibili`(`_bili` module):

| # | cap | desc/ps chars | JSON 总 chars | 实测 token | 参数 |
|---|---|---|---|---|---|
| 1 | `bilibili.search_video` | 233/153 | 495 | **224** | keyword(req) / page / page_size |
| 2 | `bilibili.get_video_info` | 326/90 | 450 | **207** | bvid / aid |
| 3 | `bilibili.search_user` | 160/119 | 386 | **156** | keyword(req) / page |
| 4 | `bilibili.get_user_videos` | 237/146 | 495 | **199** | mid(req) / page / page_size |
| 5 | `bilibili.hot_videos` | 146/97 | 349 | **154** | page / page_size |
| 6 | `bilibili.get_ranking` | 209/148 | 464 | **219** | rank_type / day |
| 7 | `bilibili.get_subtitles` | 461/90 | 455 | **230** | bvid / aid |
| 8 | `bilibili.get_my_history` | 182/68 | 359 | **152** | page_size |
| 9 | `bilibili.get_my_followings` | 156/97 | 365 | **137** | page / page_size |
| 10 | `bilibili.get_later_watch` | 136/36 | 279 | **114** | (无) |
| 11 | `bilibili.get_favorites` | 134/36 | 275 | **121** | (无) |
| **合计** | | | **4,394** | **1,924** | 8 类参数(去重) |

**关键观察**:
- 11 cap baseline 实测 **1,924 token**(avg 175/cap,与 apple_calendar avg 182 接近)
- 参数维度去重 8 类:`keyword / page / page_size / bvid / aid / mid / rank_type / day` + 单独的 `page_size` only 系列
- 长 desc cap:get_subtitles(461 desc) / get_video_info(326 desc) — 已在 P2 desc 精简覆盖,后续 fold 后 dispatcher 单一 description 重写
- 2 cap 无参(get_later_watch / get_favorites)
- 4 cap 含 req 字段(search_video.keyword / search_user.keyword / get_user_videos.mid / get_subtitles 二选一 bvid/aid)

### 1.2 双 grep audit (lesson #7 应用)

#### Mode 1 · cap-name pattern (`bilibili.<action>`)

```bash
grep -rn "bilibili\." backend/ frontend/ --exclude docs/INVESTIGATION* --exclude docs/archive*
```

| # | 文件:行 | 类型 | 处理 |
|---|---|---|---|
| **必改 active** | | | |
| 1 | `tool_addendum.py:100-114` | 8 处 LLM 引导文(B 站 8 个场景 → bilibili.<action>) | **改**(全 `→ bilibili(action="...")` 形态) |
| **frontend label-mapping(⚠️ 新发现)** | | | |
| 2 | `frontend/src/lib/tool_labels.ts:31` | `{ prefix: 'bilibili.', label: '看视频信息…' }` | **失 mapping** — fold 后 cap name `bilibili` 单字,`'bilibili'.startsWith('bilibili.')` = false → 用户 loading 时见 fallback "查询中…" 而非 "看视频信息…"(详 §1.3 ⚠️ 块) |
| **archeology(保留不动)** | | | |
| 3 | `chat.py:899-902` | docstring 数据估算注释 | 保留 |
| 4 | `integrations/bilibili.py:120,203,239+` | docstring 含"bilibili.com"域名 + URL 字符串拼接 | 与 fold 无关 |
| 5 | `services/activity_timeline.py:117,402` | 字符串"bilibili.com"字面 | 与 fold 无关 |

#### Mode 2 · Python module import pattern

```bash
grep -rn "from backend.capabilities.bilibili\|import bilibili" backend/
```

**零反向 import 命中**(`integrations/bilibili.py:48` 是 import 三方 `bilibili_api` package,**不是** backend.capabilities.bilibili)。

→ **P1.bilibili 比 apple_calendar 简单**:无 Python module import 反向 caller,**不需要 alias 兜底**。

### 1.3 dispatcher 适配 (模板 6 要点继承 + bilibili 特异点 + ⚠️ frontend label 同款问题)

#### 模板继承(§2.7.4 lock + lesson #7/#8 应用)

- 入口 cap 命名:**`bilibili`**(单字)
- 参数 union 策略:**单层 union schema**
- 错误处理:**`{ok:bool, error:str}`** 标准
- action 命名风格:**snake_case**(1:1 mapping cap suffix)
- 退役方案:**clean cut**
- smoke 三档:**ToolRegistry / LLM 真 query / dispatcher routing**
- audit 双 grep ✅ 已应用

#### 特异 a · action enum 11 项

`search_video / get_video_info / search_user / get_user_videos / hot_videos / get_ranking / get_subtitles / get_my_history / get_my_followings / get_later_watch / get_favorites`

(1:1 mapping cap suffix)

#### 特异 b · union schema 字段(8 字段)

去重后 8 个 union 参数:

| 参数 | 类型 | 哪些 action 用 | 哪些 action req |
|---|---|---|---|
| `keyword` | string | search_video / search_user | search_video, search_user |
| `bvid` | string | get_video_info / get_subtitles | (二选一) |
| `aid` | integer | get_video_info / get_subtitles | (二选一) |
| `mid` | integer | get_user_videos | get_user_videos |
| `page` | integer | search_video / search_user / get_user_videos / hot_videos / get_my_followings | (有 default 1) |
| `page_size` | integer | search_video / get_user_videos / hot_videos / get_my_history / get_my_followings | (有 default 20) |
| `rank_type` | string | get_ranking | (有 default 'all') |
| `day` | integer | get_ranking | (有 default 3) |

**dispatcher 内部校验**:
- search_video: 必填 keyword
- search_user: 必填 keyword
- get_user_videos: 必填 mid
- get_video_info / get_subtitles: bvid / aid 二选一(至少有一个)
- 其它 action 无必填(或仅有 default 参数)

#### 特异 c · ⚠️ frontend tool_labels.ts 同款问题(**新发现,P1.media 时已引入但漏修**)

`frontend/src/lib/tool_labels.ts:19-52` TOOL_LABEL_TABLE 用 `tool_name.startsWith(entry.prefix)` match:

```typescript
{ prefix: 'media.',         label: '控制播放…' },      // P1.media fold 后 'media'.startsWith('media.') = false
{ prefix: 'apple_calendar.', label: '查日历…' },      // P1.apple_calendar fold 后同款问题
{ prefix: 'bilibili.',      label: '看视频信息…' },   // P1.bilibili fold 后同款问题
```

→ **fold 后 cap name 单字,丢 `.` 后缀,prefix 全失 mapping → loading 时显示 fallback "查询中…"**。

P1.media + P1.apple_calendar **已经引入此 regression**,只是非 hard error,UX 降级而已(loading label 模糊化)。INV-6 §2/§3 commit 漏了此点 — 与 lesson #7 同款 audit 漏点(frontend startsWith 模式与 cap-name grep / module import grep 都不同)。

##### 修法选项

| 选项 | 描述 | 评估 |
|---|---|---|
| **A · 改 prefix 去掉末尾 `.`** | `'media' / 'apple_calendar' / 'bilibili'`,startsWith 兼容单字 + 多字 | 简单 zero-risk;新匹配 `'media'` 单字 + `'media.X'` 兼容(无现有 'media_X' cap collision) |
| B · 加新 entry 单独 match 单字 | 保留 `'bilibili.'` + 加 `'bilibili'` exact match | 行数翻倍,信息冗余 |
| C · 引擎从 startsWith 改 namespace 拆分 | 重构 toolLoadingLabel 用 split('.')[0] | 工程量大,超本刀范围 |

**CC 倾向 A**(改 3 个 prefix 去 `.`),理由:
- 最小改动(3 行 prefix 去尾 dot)
- startsWith 语义不破:`'media'.startsWith('media')` = true / `'media_something'.startsWith('media')` = true(假设未来无 collision,实际生产无此 prefix cap)
- 顺手补 P1.media + P1.apple_calendar 漏修(共 3 处 prefix:media / apple_calendar / bilibili)
- frontend 注释一句话标注 fold 兼容(无需 frontend rebuild,纯 TS 改 .ts 文件需要 yarn build,但**用户当前生产 frontend 已 build,UX 降级是 forward fix,等下次正式 build 时上**)

##### ⚠️ frontend build 提醒

`tool_labels.ts` 改后**需要 `yarn build` 重新构建前端**才能在生产 UI 生效(per P1.media/P1.apple_calendar 同款 — 实际改 .ts 文件本来就要 build)。但因为是 UI label 文案级 fix(非 hard breakage),**可挂着等用户下次正式 build 时一起上**,与本 commit ship 不阻塞。

→ §1.4 实施 plan 包含此选项 A 修法 + frontend build 提醒;PM Stage 1 拍板"是否合并 fix"。

### 1.4 实施 plan (待 Stage 2)

#### 改动文件清单

| # | 文件 | 改动 | diff 估 |
|---|---|---|---|
| 1 | `backend/capabilities/bilibili.py` | 删 11 旧 cap decorator + handler(~600 行)→ 改 handler 名 `_handle_*` + 新增 1 dispatcher cap + `bilibili_dispatch` 函数 + `_BILIBILI_ACTION_HANDLERS` dict;保留底层 `_bili` 引用 + health_check | 删 ~600 / 加 ~250 = 净减 ~350 行 |
| 2 | `backend/agents/prompt/tool_addendum.py:100-114` | 8 处 LLM 引导文微改 `→ bilibili.X` → `→ bilibili(action="X")` | +8 / -8 |
| 3 | `frontend/src/lib/tool_labels.ts:31` (+ media, apple_calendar 同改) | ⚠️ 3 处 prefix 去 `.`(顺手补 P1.media/P1.apple_calendar 漏修);CC 倾向 option A | +3 / -3 (注释微改) |

#### dispatcher handler 实现思路

模板 6 要点直接复用 P1.apple_calendar pattern:

```python
_BILIBILI_ACTION_HANDLERS = {
    "search_video":      _handle_search_video,
    "get_video_info":    _handle_get_video_info,
    ...
}

@register_capability(
    name="bilibili",
    display_name="B 站操作",
    description=(
        "B 站操作集合。按 action 选:\n"
        "- search_video / search_user / get_video_info / get_subtitles / ...\n"
        "..."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [...11 项]},
            "keyword": {...}, "bvid": {...}, ...,  # 8 union 字段
        },
        "required": ["action"],
    },
)
async def bilibili_dispatch(action: str = "", **params) -> dict | list[dict]:
    handler = _BILIBILI_ACTION_HANDLERS.get(action)
    if handler is None:
        return {"ok": False, "error": f"unknown action: {action!r}; valid: [...]"}
    # action-specific required 字段校验
    if action in ("search_video", "search_user"):
        if not params.get("keyword"):
            return {"ok": False, "error": f"keyword required when action={action}"}
    elif action == "get_user_videos":
        if not params.get("mid"):
            return {"ok": False, "error": "mid required when action=get_user_videos"}
    elif action in ("get_video_info", "get_subtitles"):
        if not params.get("bvid") and not params.get("aid"):
            return {"ok": False, "error": f"bvid or aid required when action={action}"}
    return await handler(**params)
```

11 个 `_handle_*` internal 函数 = 现有 handler 逻辑搬过来去掉装饰器。

### 1.5 风险评估

| 项 | 风险 | 说明 |
|---|---|---|
| LLM 调用新 dispatcher | **低** | P1.media + P1.apple_calendar 已实证 LLM 走新 cap;bilibili 11 action 是最复杂的 enum,但 LLM 模式识别能力对 11 项可控 |
| LLM 误调旧 cap 名 | **低** | 删除后 LLM 看不到 schema 不会调;unknown-tool fallback 兜底 |
| dispatcher 内部参数校验 | **极低** | 4 类必填(search keyword / user mid / video bvid-or-aid)清晰列出 |
| 现有 Python module import | **零** | grep mode 2 实测零反向 import(不像 apple_calendar 的 calendar router 需 alias) |
| ⚠️ frontend tool_labels 同款 startsWith 失 mapping | **低** | UX 降级(loading 文案 fallback "查询中…"),非 hard error;P1.media + P1.apple_calendar 已默认引入此 regression — option A 顺手修 3 处 prefix 一次性补 |
| LiteLLM × DashScope 11 enum union schema 兼容 | **极低** | 模板已实证;11 enum + 8 union 字段是 OpenAI 标准 function-calling schema |

**总风险 = 低**,可 clean cut + 选项 A 顺手修 frontend label。

### 1.6 估省 token (按 lesson #8 实写 dispatcher 估算)

**baseline 实测**:bilibili 11 cap = **1,924 token**(JSON chars 4,394,密度 0.44 token/char)

**折叠后 dispatcher 预估**(按 lesson #8 实写 chars,非 ratio 估):

| 段 | chars 估 | 备注 |
|---|---|---|
| description | ~700 | 列 11 action 名 + 短描述 + 用法引导(get_subtitles 杀手 use case / 二选一 bvid/aid / search 两步流程引导) |
| parameters_schema | ~1,500 | action enum(11 项 + description) + 8 union 字段 × ~150 chars/字段(包含 type/min/max/default/desc) |
| function-calling wrap | ~80 | JSON 包装 |
| **合计** | **~2,280** | |

× ~0.45 token/char(混合 schema 密度,bilibili 实测 0.44 + 长 description 段略高) = **~1,030 token**

**估省 = 1,924 - 1,030 = ~894 token**(中位数 **~900 token**)

vs §3 原估 -2,150,**实际是预估 ~2.4x 偏低**(与 lesson #8 校正方向一致;bilibili 比 apple_calendar 的 dispatcher schema 大 ~2x 因 8 字段 union + 11 action enum)。

按 lesson #8 校正范围 -600 到 -1,500 → **实测中位数 ~900 落在范围内**(略偏中上)。

### 1.7 收口 (Stage 1)

- ✅ 11 cap audit(JSON chars 4,394 / token 1,924 / avg 175;long-desc cap get_subtitles 461 / get_video_info 326)
- ✅ 双 grep audit(lesson #7 应用):mode 1 cap-name 必改 8 处 LLM 引导 + ⚠️ frontend tool_labels 同款 startsWith 失 mapping(P1.media/P1.apple_calendar 已默认引入);mode 2 module import 零反向 caller(无需 alias)
- ✅ dispatcher 适配:模板 6 要点继承 + 特异 3 点(11 action enum / 8 union 字段含必填校验 / ⚠️ frontend label option A 顺手修)
- ✅ 实施 plan 3 文件改动清单(bilibili.py 主结构 + tool_addendum 8 处 + tool_labels.ts 3 处 prefix)
- ✅ 风险评估 = 低
- ✅ 估省 ~900 token(按 lesson #8 实写 chars 估算,远低于 §3 原估 ~2,150,与 lesson #8 校正方向一致)

→ **Stage 1 完成,等 PM 审 + 进 Stage 2 落代码**。

特异 ⚠️ 待 PM 拍板:
- frontend tool_labels.ts option A 修法(顺手补 P1.media + P1.apple_calendar 同款漏修)是否合并入 P1.bilibili Stage 2 commit?
- 还是独立刀单 ship?

### 1.7 Stage 2 实施记录(2026-05-21)

#### 1.7.1 Commit + 改动

- commit:(本 commit) `refactor(capabilities): fold bilibili 11 caps into dispatcher (saves ~1,169 tokens, P1 template reuse #2; frontend label retro-fix included)`

PM 2026-05-21 三件拍板:
- frontend option A · 采纳合并入本 commit(含 P1.media + P1.apple_calendar retroactive 修正)
- 估省 ~900 token · ack(实测 -1,169 超中位数 ~30%)
- lesson #9 · 采纳,本节收口 + header reference list 标 #7/#8 继承 + #9 新增

| 文件 | 改动 | 大小 |
|---|---|---|
| `backend/capabilities/bilibili.py` | 删 11 旧 cap decorator + 11 handler;新增 1 dispatcher decorator + `bilibili_dispatch` + 11 `_handle_*` internal + `_BILIBILI_ACTION_HANDLERS` dict + 5 类必填校验 | -370 / +175 = 净减 ~195 行 |
| `backend/agents/prompt/tool_addendum.py:100-114` | 8 处引导文 `→ bilibili.X` → `→ bilibili(action="X", ...)` | +8 / -8 |
| `frontend/src/lib/tool_labels.ts:19-52` | 3 处 prefix 去末尾 `.`(option A retro-fix:media / apple_calendar / bilibili)+ 注释说明 fold 兼容 | +9 / -3 |

#### 1.7.2 三条 smoke 全 PASS

##### Smoke 1 · ToolRegistry

```
bilibili* cap in registry: ['bilibili']
_get_all_tools count: 40 (was 50; 净减 10:11 删 + 1 加)
tools_schema POST-P1.bilibili: 8,437 tokens (P1.apple_calendar baseline 9,606)
P1.bilibili reduction: 1,169 tokens
```

##### Smoke 2 · LLM 调用 dispatcher(11 action 全覆盖)

11 query 各发一次,**11/11 调 bilibili dispatcher**:

```
[ 1] expect=search_video       → ['bilibili'] ✅
[ 2] expect=get_video_info     → ['bilibili'] ✅ (retry 用真 BV URL 后)
[ 3] expect=search_user        → ['bilibili'] ✅
[ 4] expect=get_user_videos    → ['bilibili'] ✅
[ 5] expect=hot_videos         → ['bilibili'] ✅
[ 6] expect=get_ranking        → ['bilibili'] ✅
[ 7] expect=get_subtitles      → ['bilibili', 'bilibili'] ✅ (retry 用真 BV URL 后,LLM 链路调 2 次)
[ 8] expect=get_my_history     → ['bilibili'] ✅
[ 9] expect=get_my_followings  → ['bilibili'] ✅
[10] expect=get_later_watch    → ['bilibili'] ✅
[11] expect=get_favorites      → ['bilibili'] ✅
```

初跑 [2] 和 [7] 用占位 BV(`BVxxx` / `BV1xx`)LLM 合理拒调(LLM 行为正确,不调假数据上的工具);用真 BV URL 形式 `bilibili.com/video/BV1uv411B7tH` 重跑后 **11/11 全 ✅**。

##### Smoke 3 · dispatcher routing 6 档

```
unknown action          → {ok: False, error: "unknown action: 'unknown_X'; valid: [...11 项]"}
search_video no keyword → {ok: False, error: "keyword required when action=search_video"}
search_user no keyword  → {ok: False, error: "keyword required when action=search_user"}
get_user_videos no mid  → {ok: False, error: "mid required when action=get_user_videos"}
get_video_info no bvid/aid → {ok: False, error: "bvid or aid required when action=get_video_info"}
get_subtitles no bvid/aid  → {ok: False, error: "bvid or aid required when action=get_subtitles"}
hot_videos real routing → type=dict, keys=['result', 'page']  ✅ 真路由到 _bili.hot_videos
```

✅ 6 档(unknown + 5 必填校验 + 真 routing)全正确。

#### 1.7.3 token 减幅累计

| 阶段 | tools_schema token | 累计减幅 vs INV-3 §③ 13,250 baseline |
|---|---|---|
| INV-3 §③ baseline | 13,250 | 0 |
| P2 (`72808ef`) | 10,336 | -2,914 (22.0%) |
| P3 (`81205f5`) | 9,954 | -3,296 (24.9%) |
| P1.media (`a835677`) | 9,697 | -3,553 (26.8%) |
| P1.apple_calendar (`f20a931`) | 9,606 | -3,644 (27.5%) |
| **P1.bilibili (本 commit)** | **8,437** | **-4,813 (36.3%)** |

P1.bilibili 单刀 **-1,169 token**,**超 PM 预期 -900 中位数 ~30%**。dispatcher 实写比 §1.6 估算的 ~1,030 token 更精简(实测 ~1,000-ish,但 baseline 也比 11×175=1,924 稍高:实际整 schema list JSON wrap 含 separator overhead)。

lesson #8 校正方向反转出现:bilibili 这种 long-desc cap 多的 group,dispatcher 单一 description 取代 11 个 long desc,**reduction 大于预估**。

#### 1.7.4 frontend retro-fix 详注

`frontend/src/lib/tool_labels.ts` 改 3 处 prefix 去 `.`,补 P1.media + P1.apple_calendar + P1.bilibili 同款 fold-后失 mapping 漏修:

```typescript
{ prefix: 'apple_calendar', label: '查日历…' },  // INV-7 §1.7 retro-fix
{ prefix: 'bilibili', label: '看视频信息…' },   // INV-7 §1.7 retro-fix
{ prefix: 'media', label: '控制播放…' },        // INV-7 §1.7 retro-fix
```

`'media'.startsWith('media')` = true(fold 后单字命中);`'media.next_track'.startsWith('media')` = true(假设 fold 前 / 未来多字仍兼容);**无 prefix collision**(生产无 `media_X` / `bilibili_X` / `apple_calendar_X` 系列 cap)。

⚠️ **改后需 frontend `yarn build` 才在生产 UI 生效**;本 commit 不触发 build,**挂着等 PM 任何时候 yarn build**。当前生产 UX 降级状态(loading label 显 fallback "查询中…"而非具体文案)持续到下次 frontend rebuild。

#### 1.7.5 Lesson #9 · frontend startsWith 模式与 cap-name grep / module import grep 都不同

**新发现**(P1.bilibili Stage 1 audit 实测):前端 / 其它 layer 可能用 `startsWith(prefix + '.')` 形式匹配 cap-name,fold 单字 namespace 后(cap name 无 `.`),prefix match 失效 → UX 降级 / fallback。

- P1.media 已默认引入此 regression(commit `a835677` 漏修)
- P1.apple_calendar 已默认引入此 regression(commit `f20a931` 漏修)
- P1.bilibili Stage 1 audit 暴露 + Stage 2 顺手 retro-fix 补三处

**后续 P1.netease(子轨 B 收尾刀)Stage 1 audit 必走三 grep 模式**:
1. cap-name pattern(`netease.<action>`)
2. Python module import pattern(`from backend.capabilities.netease_music / netease_playback import`)
3. **frontend startsWith pattern**(`startsWith\('netease\.'\)` / `prefix: 'netease.'`)

**Lesson 抽象**:

> dispatcher fold 后,凡是 backend / frontend / docs 任何地方按 `<group>.` prefix match 的 string-level pattern,**fold 后单字 cap name 无 `.` 必然失 mapping**。Stage 1 audit 必走完整三 grep:cap-name / module import / frontend prefix。

#### 1.7.6 收口

- ✅ 3 文件改动 ship(bilibili.py 11→1 主结构 + tool_addendum 8 处微改 + tool_labels.ts 3 处 retro-fix)
- ✅ 3 条 smoke 全 PASS(11 LLM query 100% 调新 bilibili dispatcher + 6 档 dispatcher routing)
- ✅ 实测 -1,169 token(超 PM 预期 ~900 中位数 ~30%),累计 36.3% reduction
- ✅ frontend retro-fix 顺手补 P1.media + P1.apple_calendar 同款漏修(需 yarn build 才生效)
- ✅ lesson #9 三 grep 模式记入(后续 P1.netease 必走)
- 🔒 零 backend cap regression / handler 逻辑改动

→ **P1.bilibili 子轨 B 实施第 5 刀 closed**。下一刀 = **P1.netease 13→2 双 dispatcher**(子轨 B 收尾刀,模板复用 #3 + 双 path 设计),Stage 1 必走三 grep audit。

---

## §2 P1.netease 13→2 双 dispatcher 入口折叠 (Stage 1 草稿, 2026-05-21)

> P1 入口折叠**第 4 刀 / 子轨 B 收尾刀**;模板复用 #3 + 双 path 设计;lesson #7/#8/#9 全继承;**新发现 lesson #10 候选**(capability-tag fallback regex)。

### 2.1 13 cap audit + 双 dispatcher 分组

按 INV-4 §3.1.2 D1 决策分组(web URL Scheme path / local mpv 自解码 path 底层不同):

#### web group (`netease_music.py` 7 cap)

| # | cap | token | 参数 |
|---|---|---|---|
| 1 | `netease.daily_recommend` | **204** | (无) |
| 2 | `netease.personal_fm` | **182** | (无) |
| 3 | `netease.play_song` | **189** | keyword(req) |
| 4 | `netease.play_playlist` | **205** | (无) |
| 5 | `netease.play_playlist_by_id` | **148** | playlist_id(req) |
| 6 | `netease.like_current` | **222** | title(req) / artist |
| 7 | `netease.search` | **195** | keyword(req) / search_type / limit |
| **web subtotal** | | **1,345** | 6 类 union 参数(去重) |

#### local group (`netease_playback.py` 6 cap)

| # | cap | token | 参数 |
|---|---|---|---|
| 8 | `netease.local_play_song` | **203** | song_id(req) |
| 9 | `netease.local_play_playlist` | **233** | playlist_id(req) / limit |
| 10 | `netease.local_pause` | **126** | (无) |
| 11 | `netease.local_resume` | **77** | (无) |
| 12 | `netease.local_stop` | **103** | (无) |
| 13 | `netease.local_next_in_queue` | **152** | (无) |
| **local subtotal** | | **894** | 3 类 union 参数(去重) |

**total baseline**:**2,239 token**(JSON chars 4,860,实测 2,250 含 list separator overhead;平均 173/cap 接近 bilibili avg 175)

**关键分布**:
- web 含 long-desc cap(daily_recommend 393 chars desc / personal_fm 304 / like_current 多步前置)→ **类 bilibili pattern**(ROI 偏高)
- local 含 long-desc cap(local_play_song 297 / local_play_playlist 285),但 4 个无参 cap 短 → **混合 pattern**

### 2.2 三 grep audit (lesson #7 + #9 三维强制)

#### Mode 1 · cap-name pattern (`netease.X`)

**必改 active**(LLM runtime 引导文):

| # | 文件:行 | 内容 |
|---|---|---|
| 1 | `tool_addendum.py:40-49` | web 引导段 5+1 处提及 `netease.daily_recommend / personal_fm / play_song / play_playlist / play_playlist_by_id / search / like_current` |
| 2 | `tool_addendum.py:85-94` | local 引导段 5 处 `netease.search / local_play_song / local_play_playlist / local_pause / local_resume / local_stop` |

合计 ~11 行 LLM 引导文必改。

**archeology(保留作历史 / sanitize chain 引用)**:

- `chat.py:902` docstring 数据估算注释
- `database/migrations/v3_5_chunk6b_hotfix3_clean_polluted_memories.py` 历史 migration(`<netease.daily_recommend>` 字面)
- `capabilities/media_control.py:87` docstring `复用同一份解析`
- `config/__init__.py:30` `netease_music_u` env field
- `integrations/netease_music.py:18,124` self-reference

**⚠️ 真 runtime sanitize 路径(详 §2.2.4)**:
- `tool_call_resilience.py:11,87-89` capability-name-as-tag fallback 注释
- `text_filters.py:113-114,398,413` sanitize chain 处理 `<netease.X />` LLM 错乱 tag

#### Mode 2 · Python module import

```bash
grep -rn "from backend.capabilities.netease_music\|from backend.capabilities.netease_playback" backend/
```

**零反向 import handler 函数**:
- `backend/main.py:185, 192` import module(触发 `@register_capability` 装饰器副作用),**不是** import 函数;module-level import 不会因函数改名 break(import 整个模块,LLM-facing cap name 改后 ToolRegistry by-name dispatch 仍 work)
- `backend/integrations/bilibili.py:3` docstring 提及 netease 设计同模式(无 import)

→ **不需要 alias 兜底**(不像 apple_calendar / calendar.py:43,55 的反向 import handler 名场景)。

#### Mode 3 · frontend prefix startsWith

```bash
grep -rn "'netease\|\"netease" frontend/
```

| # | 文件:行 | 内容 | 处理 |
|---|---|---|---|
| 1 | `frontend/src/lib/tool_labels.ts:37` | `{ prefix: 'netease.', label: '查歌单…' }` | **必改 retro-fix**(同 P1.bilibili Stage 2 模式,fold 后 cap name 单字 `netease_web` / `netease_local` 失 startsWith match 命中) |

#### ⚠️ 新发现:lesson #10 候选(capability-tag fallback regex)

`backend/agents/tool_call_resilience.py:100-104 _CAPABILITY_TAG_RE`:

```python
_CAPABILITY_TAG_RE = re.compile(
    r"<([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)"   # group 1: 含 dot 的 cap name
    r"(?:\s+[^>]*?)?"
    r"(?:\s*/>|>(.*?)</\1>)",
    re.DOTALL | re.IGNORECASE,
)
```

`backend/utils/text_filters.py:402-406 _CAPABILITY_OPEN_TAG_RE` 同款 `.` 必填模式。

**功能**:Qwen 偶发把 capability name 当 XML tag 输出(`<netease.daily_recommend>...</netease.daily_recommend>`)→ resilience 提取 tag → 调对应 cap;text_filters 用同款 regex 把这种"capability-name-as-tag"从 chat_history 里 strip 防 in-context 自循环。

**fold 后**:cap name 单字 `netease_web` / `netease_local` **无 `.`**,LLM 若错误回退输出 `<netease_web>` 形态 → 这两个 regex **拒匹配**(require `.`) → fallback 失效。

**评估**:
- 该 regex 是 **hotfix-3 错误回退兜底**(LLM 正常应直接调 tool_call,不应输出 cap-as-tag);P1.media / apple_calendar / bilibili 已 ship,实测 LLM 全部走新 dispatcher 不触发此 fallback 路径(无观察到错误回退)
- 双面性:fold 后该 fallback 自然失效**符合预期**(LLM 学新单字形态,旧含-dot 错误回退本就不该发生);但若 LLM 在某些边缘情况错误回退到 `<netease_web>`,resilience strip + dispatch 不工作 → 字面字符进 chat_history 污染 in-context

**CC 倾向 lesson #10 接受 fallback 失效作 fold trade-off**(与 P1.media / apple_calendar / bilibili 已 ship 路径一致;无新代码改动)。若 PM 想保 fallback 覆盖单字 cap name → 改 regex 容忍 `[a-z_][a-z_0-9]*` 不必含 `.`(独立小 PR,可挂 P1.netease ship 之后议)。

### 2.3 双 dispatcher 适配(模板继承 + netease 特异)

#### 模板继承(§2.7.4 lock + lesson #7/#8/#9 全应用)

- 单层 union schema(each dispatcher 独立)
- `{ok:bool, error:str}` 标准
- snake_case action(1:1 mapping cap suffix,但去掉 `local_` prefix:`play_song / play_playlist / pause / resume / stop / next_in_queue`)
- clean cut
- smoke 三档 + lesson #9 三 grep 已走

#### 特异 a · 双 dispatcher 命名

**CC 倾向 lock**:
- `netease_web`(7 cap)
- `netease_local`(6 cap)

理由:
- 单字 namespace(与 media / apple_calendar / bilibili fold 后命名风格统一)
- `web` / `local` 后缀清楚标识两条 path 底层差异(web URL Scheme / local mpv)
- LLM 调用形态:`netease_web(action="play_song", keyword="X")` / `netease_local(action="play_song", song_id=N)`

#### 特异 b · 两 dispatcher 独立 action enum

**netease_web 7 action**:
`daily_recommend / personal_fm / play_song / play_playlist / play_playlist_by_id / like_current / search`

**netease_local 6 action**(去掉 `local_` prefix):
`play_song / play_playlist / pause / resume / stop / next_in_queue`

注意:web 和 local 都有 `play_song` / `play_playlist` action 名,但属于**不同 dispatcher**,无 collision(LLM 看 dispatcher name 区分)。

#### 特异 c · 两 dispatcher 独立 union schema

**netease_web union 字段(6 类去重)**:

```python
parameters_schema = {
    "type": "object",
    "properties": {
        "action": {"enum": ["daily_recommend", "personal_fm", "play_song",
                            "play_playlist", "play_playlist_by_id",
                            "like_current", "search"]},
        "keyword": {"type": "string", "description": "仅 action=play_song / search 必填"},
        "playlist_id": {"type": "integer", "description": "仅 action=play_playlist_by_id 必填"},
        "title": {"type": "string", "description": "仅 action=like_current 必填"},
        "artist": {"type": "string", "description": "仅 action=like_current 可选"},
        "search_type": {"type": "string", "description": "仅 action=search 可选(默 song)"},
        "limit": {"type": "integer", "description": "仅 action=search 可选(默 5)"},
    },
    "required": ["action"]
}
```

dispatcher 内部校验:
- play_song / search: 必填 keyword
- play_playlist_by_id: 必填 playlist_id
- like_current: 必填 title

**netease_local union 字段(3 类去重)**:

```python
parameters_schema = {
    "type": "object",
    "properties": {
        "action": {"enum": ["play_song", "play_playlist", "pause", "resume", "stop", "next_in_queue"]},
        "song_id": {"type": "integer", "description": "仅 action=play_song 必填"},
        "playlist_id": {"type": "integer", "description": "仅 action=play_playlist 必填"},
        "limit": {"type": "integer", "description": "仅 action=play_playlist 可选"},
    },
    "required": ["action"]
}
```

dispatcher 内部校验:
- play_song: 必填 song_id
- play_playlist: 必填 playlist_id

#### 特异 d · frontend retro-fix(同 P1.bilibili 模式)

`tool_labels.ts:37` 单 prefix `netease.` → 拆为两 prefix(无 dot)兼容双 dispatcher:

```typescript
{ prefix: 'netease_web', label: '查歌单…' },     // INV-7 §2 P1.netease fold (web)
{ prefix: 'netease_local', label: '本地播放…' },  // INV-7 §2 P1.netease fold (local)
```

⚠️ **改后需 yarn build** 才在生产 UI 生效(同 P1.bilibili)。

### 2.4 实施 plan(待 Stage 2)

#### 改动文件清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `backend/capabilities/netease_music.py` | 删 7 旧 cap decorator + 改 7 handler 名为 `_handle_*`;新增 `_NETEASE_WEB_ACTION_HANDLERS` dict + `netease_web_dispatch` + dispatcher decorator + 3 类必填校验(keyword/playlist_id/title) |
| 2 | `backend/capabilities/netease_playback.py` | 删 6 旧 cap decorator + 改 6 handler 名为 `_handle_*`;新增 `_NETEASE_LOCAL_ACTION_HANDLERS` dict + `netease_local_dispatch` + dispatcher decorator + 2 类必填校验(song_id/playlist_id) |
| 3 | `backend/agents/prompt/tool_addendum.py:40-49 / 85-94` | ~11 处引导文 `→ netease.X` → `→ netease_web(action="X", ...)` / `→ netease_local(action="X", ...)` 微改 |
| 4 | `frontend/src/lib/tool_labels.ts:37` | 1 行 → 2 行:删 `prefix: 'netease.'`,新加 `'netease_web'` + `'netease_local'`(retro-fix per lesson #9) |

#### 估改动量

- netease_music.py: -350 / +180 ≈ 净减 ~170 行
- netease_playback.py: -300 / +160 ≈ 净减 ~140 行
- tool_addendum.py: ~+11/-11
- tool_labels.ts: +2/-1

### 2.5 风险评估

| 项 | 风险 | 说明 |
|---|---|---|
| LLM 调用新双 dispatcher(选 web vs local) | **中** | netease 是唯一双 dispatcher 设计,LLM 需正确区分 "web Scheme 路径(netease_web)" vs "mpv 本地播路径(netease_local)";tool_addendum 引导文必须清晰强调差异 |
| dispatcher 内部参数校验 | **极低** | 模板继承 + 3+2 类必填清晰 |
| 现有 caller 硬编码 | **零** | grep mode 2 实测零反向 import |
| frontend tool_labels retro-fix | **极低** | 同 P1.bilibili 模式,需 yarn build 才生效 |
| LiteLLM × DashScope 7+6 enum union schema 兼容 | **极低** | 模板已实证 |
| ⚠️ **lesson #10 capability-tag fallback regex 失效** | **低**(接受 trade-off) | fold 后 LLM 不应输出 `<netease_web>` 错误形态;若错误回退出现,sanitize strip + dispatch 不工作 → 字面进 chat_history 污染;P1.media / apple_calendar / bilibili 已 ship 同款问题无观察到 regression,接受 trade-off;后续可独立 PR 改 regex 容忍单字 |
| ⚠️ **LLM 路径混淆**(web vs local) | **中** | web 和 local 都有 `play_song` / `play_playlist` action,LLM 需正确选 dispatcher;tool_addendum 引导明示 "用户说'放 X 歌'通常选 netease_local(mpv 自动播放),除非用户指定走 NCM 客户端"(per 现 tool_addendum.py:94 引导)|

**总风险 = 中-低**;web vs local 路径选择是新引入决策点,LLM 可能初期 confused,smoke 2 必跑确认。

### 2.6 估省 token (按 lesson #8 实写估算)

#### netease_web (7 cap,类 bilibili pattern,ROI 偏高范围)

baseline: **1,345 token**

dispatcher 实写预估:
- description: ~600 chars(列 7 action + 用法引导含 mpv vs NCM 路径说明 + like_current 二步前置 media)
- parameters_schema: ~800 chars(action enum 7 + 6 类 union 字段)
- wrap: ~80 chars
- 合计 ~1,480 chars × ~0.45 token/char = **~665 token**

→ **估省 web = 1,345 - 665 = ~680 token**

#### netease_local (6 cap,混合 pattern)

baseline: **894 token**

dispatcher 实写预估:
- description: ~400 chars(列 6 action + mpv 上下文 + 与 web 路径区别说明)
- parameters_schema: ~400 chars(action enum 6 + 3 类 union 字段)
- wrap: ~80 chars
- 合计 ~880 chars × ~0.45 token/char = **~395 token**

→ **估省 local = 894 - 395 = ~500 token**

#### 合计

| dispatcher | baseline | dispatcher 预估 | 估省 |
|---|---|---|---|
| netease_web | 1,345 | ~665 | **~680** |
| netease_local | 894 | ~395 | **~500** |
| **合计** | **2,239** | **~1,060** | **~1,180 token** |

vs PM 期望 ~800-1,200 → **落上沿**(因 web group 类 bilibili pattern 偏高 ROI);vs §3 原估 -2,360 偏低 ~2x(lesson #8 校正方向一致)。

按 bilibili pattern 实测 reduction 略超预估 ~30%(本节预估 -1,180 可能实测 -1,300-1,500 上沿)。

### 2.7 收口 (Stage 1)

- ✅ 13 cap audit(JSON chars 4,860 / token 2,239 / avg 173;web 7×192=1,345 / local 6×149=894)
- ✅ 双 dispatcher 分组按 D1 决策 web/local 拆 — netease_web(7) + netease_local(6)
- ✅ 三 grep audit 完整(lesson #7 + #9 应用):
  - mode 1:11 行 LLM 引导文必改;sanitize chain 标记 lesson #10 候选
  - mode 2:零反向 import handler(不需 alias)
  - mode 3:frontend tool_labels.ts retro-fix 需新加 2 prefix
- ✅ **新发现 lesson #10**:capability-tag fallback regex `_CAPABILITY_TAG_RE` 强制 `.` 模式,fold 单字 cap 后 fallback 失效;CC 倾向接受 trade-off
- ✅ 4 文件改动 plan:netease_music / netease_playback / tool_addendum / tool_labels.ts
- ✅ 风险评估 = 中-低,主要 web vs local 路径选择需 smoke 2 confirm
- ✅ 估省 ~1,180 token(web ~680 + local ~500,落 PM 预期上沿)

→ **Stage 1 完成,等 PM 审 + 拍板**:
- 双 dispatcher 命名 `netease_web` + `netease_local` lock?
- lesson #10 接受 trade-off (CC 倾向) 还是独立 PR 改 regex?
- 进 Stage 2 落代码。

# Investigation 7 · 子轨 B 工具治理实施收尾（P1.bilibili + P1.netease）

> 接 INV-6 915 行封存（2026-05-21）。
> 模板 reference: INV-6 §2.7.4（dispatcher 6 要点）+ §3.8（lesson #7 双 grep / lesson #8 实写偏差）。
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

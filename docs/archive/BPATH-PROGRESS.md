# BPATH-PROGRESS

> B 路实施进度档案。分节 append，每节标【轮次+时间戳】。
> 本文件供用户直接交顾问核验，不 commit 由用户决定。

---

## 【轮次 1 · 2026-05-18 11:38】B路实施·三处原子改动

### 前置回顾

- 备份：`momoos.db.backup_bpath_20260518_113501`（700 416 B，与原 DB 等大）
- 顾问已豁免"工作区干净"前置：`M config.yaml`（本地调试态）+ `splash-art/102.png`（同型 untracked）—— 与本步零交集
- `stash@{0}` 未动

### 改动 1 — `backend/database/services.py:134-138`（含 `or_` 已 import）

```diff
diff --git a/backend/database/services.py b/backend/database/services.py
@@ -133,7 +133,9 @@ async def get_all_memories(
     from sqlalchemy import or_
     query = select(Memory).where(Memory.user_id == user_id)
     if character_id is not None:
-        query = query.where(Memory.character_id == character_id)
+        query = query.where(
+            or_(Memory.character_id == character_id, Memory.character_id.is_(None))
+        )
     if active_only:
         now = datetime.utcnow()
         query = query.where(
```

### 改动 2 — `backend/agents/chat.py` 两处

2a. 顶部 import 补 `or_`（L41）：

```diff
-from sqlalchemy import select
+from sqlalchemy import or_, select
```

2b. `_tool_compress_memories` 写前 fetch（L843-848）：

```diff
@@ -843,7 +843,9 @@ async def _tool_compress_memories(
         try:
             existing_q = select(Memory).where(Memory.user_id == user_id)
             if character_id is not None:
-                existing_q = existing_q.where(Memory.character_id == character_id)
+                existing_q = existing_q.where(
+                    or_(Memory.character_id == character_id, Memory.character_id.is_(None))
+                )
             existing = list((await session.execute(existing_q)).scalars().all())
             for m in existing:
                 await session.delete(m)
```

### 改动 3 — `backend/main.py:390-410` V2.5-C2c backfill 整段删除

```diff
@@ -387,27 +387,6 @@ async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
     # CREATE IF NOT EXISTS,幂等。不动 memory / 任何现存表 schema。
     await migrate_v4_0_0_memory_tombstone()
 
-    # ── 1c. V2.5-C2c backfill: legacy memory rows pre-date character_id, so
-    #         tag them as Momo's so per-character filters keep showing them.
-    from sqlalchemy import text
-    from backend.database import engine as _engine
-    async with _engine.begin() as _conn:
-        momo_id_row = (await _conn.execute(
-            text("SELECT id FROM characters WHERE name = 'Momo' LIMIT 1")
-        )).fetchone()
-        if momo_id_row is not None:
-            momo_id = int(momo_id_row[0])
-            res = await _conn.execute(
-                text("UPDATE memory SET character_id = :cid WHERE character_id IS NULL"),
-                {"cid": momo_id},
-            )
-            updated = getattr(res, "rowcount", None)
-            if updated:
-                logger.info(
-                    "[V2.5-C2c] Backfilled %d legacy memory rows -> character_id=%d (Momo)",
-                    updated, momo_id,
-                )
-
     # ── 2. Default user ──────────────────────────────────────────────────────
     default_uid: str  = config_yaml.get("default_user_id", "default")
     default_name: str = "Momo"
```

### `git status --porcelain` 全文

```
 M backend/agents/chat.py            ← 本轮 M（新增）
 M backend/database/services.py      ← 本轮 M（新增）
 M backend/main.py                   ← 本轮 M（新增）
 M config.yaml                       ← 既有 M（豁免件，未动）
?? DESIGN_patch.md
?? docs/AUDIT-GROUND-TRUTH.md
?? frontend/public/splash-art/100.png
?? frontend/public/splash-art/101.png
?? frontend/public/splash-art/102.png     ← 豁免件，未动
?? frontend/public/splash-art/2.png
?? frontend/public/splash-art/3.png
?? frontend/public/splash-art/99.png
?? momoos.db.backup_20260518_111610
?? momoos.db.backup_2bugfix_20260516_1704
?? momoos.db.backup_bindfix_20260516_1340
?? momoos.db.backup_bpath_20260518_113501  ← 本轮新增备份
?? momoos.db.backup_chatpanel_20260516_1555
?? momoos.db.backup_diag_20260517_000427
?? momoos.db.backup_memsum_20260517_015154
?? momoos.db.backup_purge_20260516_1245
?? momoos.db.backup_zh_revert_20260516_1038
?? momoos.db.before-mai-injection
?? voice_clone_local.py
```

新增的 M 只有 3 个：chat.py / services.py / main.py（指令要求）。config.yaml / 102.png 未动。
新增 untracked 只有本轮备份 `momoos.db.backup_bpath_20260518_113501`。

### 静态自查

| 检查项 | 结果 |
|---|---|
| `or_` import in services.py | ✅ 函数局部 import 在 L133（pre-existing，未动） + L321（另一函数局部，未动）|
| `or_` import in chat.py | ✅ 顶部 import 新增 L41 `from sqlalchemy import or_, select`；函数体内不再需额外 import |
| 三处语义一致 | ✅ 改动 1（services.py L137）与改动 2b（chat.py L847）使用**完全相同的表达式**：`or_(Memory.character_id == character_id, Memory.character_id.is_(None))`；改动 3 整段移除，无残留行 |
| backfill 整段干净移除 | ✅ `grep "V2.5-C2c\|UPDATE memory SET character_id" backend/main.py` 输出空；上方 `await migrate_v4_0_0_memory_tombstone()` 完整保留；下方 `# ── 2. Default user` 完整保留；中间无悬挂空行 |
| 相邻 lifespan/migration 未误删 | ✅ main.py L388 migration 调用 + L390 `# ── 2. Default user` 段紧邻，连续无断裂；其他 migration（1b32 conversation_summary / 1b33 tombstone）均未触及 |
| schema 改动 | ✅ 零（指令禁项已遵守）|
| commit / push / stash 动作 | ✅ 零（指令禁项已遵守）|
| backend 启动 / 测试 / DB 改 | ✅ 零（指令禁项已遵守）|

### 语义统一性陈述

本轮三处改动落地**原子语义**："NULL 视为跨角色共享一等公民"——

- 读端 `services.get_all_memories`：当 caller 传 `character_id=N` → 现在返回 `character_id=N` 行 + `character_id IS NULL` 行
- 读端 `chat.py:_tool_compress_memories` 写前 fetch：同上扩展
- 启动端：删除 `V2.5-C2c` backfill，不再启动时把 NULL 抹平为 Momo
- 三处共同确立："NULL = 共享" 在运行时与重启后**行为一致**，无二义性

### 改动覆盖的读路径（recon 一致）

| 路径 | 改前 default 用户 cid=1 | 改后 default 用户 cid=1 |
|---|---|---|
| UI `/api/memory/list?character_id=1` | 0 行 | 2 行（id 14/15 NULL） |
| LLM tool `list_memories` (chat.py:745) | 0 行 | 2 行 |
| LLM tool `compress_memories` fetch (chat.py:782) | 0 行 | 2 行 |
| Proactive wake_call instruction (engine.py:696) | 0 行 | 2 行（type=instruction 中 id=15 1 条） |
| 其他 6 路不带 character_id 过滤的读取 | 不变（2 行） | 不变（2 行） |

### 待真机回归（本轮不做，等顾问核 diff 后另发指令）

- 启动 backend → 验三路（UI / list_memories / wake_call）真返回 NULL 行
- 重启第二次 → 验 NULL 行仍 NULL（backfill 已删，不再抹平）
- 验 extractor 后续写入仍为 NULL（行为未变，与 B 路语义相符）

### 暂停

零 commit / 零 push / 零 stash 动作 / 零 schema 改动 / 零 backend 启动 / 零 DB 改动。等顾问核 diff。

---

## 【轮次 2-中止 · 2026-05-18 14:08】基线追因 · 第二抹平点定位

### 中止原因

真机回归 Step 1 实测：memory id=14/15 的 character_id **已是 `1`，不是 NULL**——预期"仍 cid=NULL"被打破。需先定位 11:35 备份之后是谁把 NULL→1，否则后续验证失去鉴别力。

### Q1 — DB 时间线

| 文件 | size | mtime | character_id of 14/15 |
|---|---|---|---|
| `momoos.db.backup_20260518_111610` | 700 416 | 5月 18 11:16 | NULL |
| `momoos.db.backup_bpath_20260518_113501`（B 路改动后即刻备份） | 700 416 | 5月 18 11:35 | NULL |
| **当前 `momoos.db`** | 700 416 | **5月 18 13:53** | **1** |
| `momoos.db.backup_bpath_verify_20260518_140550` | 700 416 | 5月 18 14:05 | 1 |

→ **11:35 之后、13:53 之前，有人/有程序对 memory.character_id 做了 NULL→1 写入**。

### Q2 — backend 进程 / pyc / 日志

- `ps -axo` 当前**无任何 python/uvicorn/backend 进程**
- `lsof momoos.db` **空**（无进程持有 DB）
- 仓库内无 `.log/.out/.err` 文件——后端 stdout 应该直接打到终端，无落盘
- **关键证据**：受影响 .pyc mtime 显示 backend **在 11:39-11:40 之间被启动过一次**
  - `backend/__pycache__/main.cpython-310.pyc` mtime = 11:40
  - `backend/database/__pycache__/services.cpython-310.pyc` mtime = 11:39
  - `backend/agents/__pycache__/chat.cpython-310.pyc` mtime = 11:39
  - 源文件（chat.py / services.py / main.py）mtime 全 11:39（B 路改动时间）→ .pyc 11:39-40 是 **B 路改动后立即首次 import** 留下的
- DB mtime=13:53 比 .pyc 启动时间晚 2h13min → backend 至少从 11:40 起跑了一段时间，期间或之后某刻有 DB 写

### Q3 — 第二抹平点扫描 🎯 找到根因

全代码库 `UPDATE memory SET character_id` 扫：

```
backend/database/migrations/v2_5_b.py:114
    text("UPDATE memory SET character_id = :cid WHERE character_id IS NULL"),
backend/database/migrations/v3_5_chunk6b_hotfix3_clean_polluted_memories.py:142
    (不相关：UPDATE content WHERE id)
backend/database/migrations/v3_5_chunk9_memory_forgetting_curve.py:79
    (不相关：UPDATE last_accessed_at)
backend/memory/long_term.py:240
    (不相关：UPDATE access_count)
```

**`backend/database/migrations/v2_5_b.py:108-116`** 是 V2.5-C2c **之外的第二处** `UPDATE memory.character_id WHERE IS NULL` 抹平：

```python
# v2_5_b.py:108-116
# --- 8. backfill character_id / conversation_id on existing rows ------
await conn.execute(
    text("UPDATE chat_history SET character_id = :cid WHERE character_id IS NULL"),
    {"cid": char_id},
)
await conn.execute(
    text("UPDATE memory SET character_id = :cid WHERE character_id IS NULL"),
    {"cid": char_id},
)
```

调用链：`backend/main.py:33` import + `backend/main.py:221` `await migrate_v2_5_b()` ——**lifespan 1aXX 阶段（早于 v4 系列 migration / 已删 V2.5-C2c 之前）每次启动都跑**。

`char_id` 从 v2_5_b.py:71-88 显式 SELECT Momo 的 id → 写入值 = 1。

**结论**：本轮 B 路改动 3（删 V2.5-C2c backfill）**只删了 lifespan 中后面那一处 backfill**，**未触及更早的 v2_5_b migration 内的同语义 UPDATE**。所以 11:40 那次启动跑 `migrate_v2_5_b()` → UPDATE 14/15 NULL → 1 → DB 落盘。13:53 这个 mtime 可能是后续 extractor / 其他写入触发的（与 NULL→1 这件事无关）。

### Q4 — main.py 磁盘内容核

```
grep "V2.5-C2c\|UPDATE memory SET character_id\|Backfilled %d legacy" backend/main.py
(空输出)
```

`sed -n '385,400p'` 实读边界区段：`await migrate_v4_0_0_memory_tombstone()` 紧接 `# ── 2. Default user` ——backfill 整段干净移除，无残留行、无悬挂空行。**改在了正确的文件，已正确持久化**。

### Q5 — 多实例 / 副本 / 软链

- 仓库内还有一处 `frontend/momoos.db`——**0 字节空文件**，mtime 5月15 23:21，无 `memory` 表，不同 inode（无硬链）。**与本案无关**，是某次在 frontend/ cwd 跑出来的空 sqlite 伪影
- 软链：仅 `.venv/bin/python*` 三条指向 python 解释器；无 DB 相关软链
- DB URL 配置：`backend/config/__init__.py:29` `database_url: str = "sqlite+aiosqlite:///./momoos.db"` —— **相对 cwd**；若从 frontend/ 启动会落到 `frontend/momoos.db`。但当前现象是 root `momoos.db` 被改了 → backend 从 root cwd 启动，与预期一致

### 根因汇总

| 项 | 状态 |
|---|---|
| B 路改动 3 删除 main.py V2.5-C2c backfill | ✅ 已干净落盘 |
| **同语义第二处 backfill 在 v2_5_b.py:113-115** | ❌ **未删，仍每次启动触发** |
| backend 11:40 启动跑 migrate_v2_5_b() → UPDATE NULL→1 | ✅ 实证（pyc + DB mtime + 数据状态三角对账） |
| 多 DB 实例 / 软链 / 进程持有 | ❌ 否，排除 |

### 处置方向（人工裁决）

| 方案 | 措辞 |
|---|---|
| 1 | 把 `v2_5_b.py:113-116` UPDATE memory 那两行（也包括 chat_history 那一行）一并按 B 路语义删除——彻底落实"NULL = 共享" |
| 2 | 给 v2_5_b backfill 加 idempotency guard（如 schema_version 表，跑过一次后跳过）——既保留 legacy first-startup 兼容，又不再每次重跑 |
| 3 | 把"NULL = 共享"语义写入 v2_5_b 注释 + 删 UPDATE memory 那一行；保留 chat_history 那条（chat_history 的 character_id 语义可能不同，本节未深入）|

### B 路当前状态

- 代码改动 1 / 2（读端 `or_` 包装）在 backend 11:40 启动后**已生效**，但 14/15 行此刻 character_id=1 → "1 OR NULL" 命中 cid=1，B 路扩展分支未被触发用上（NULL 没了，全是 1）
- 改动 3（删 V2.5-C2c）有效但被改动 v2_5_b（未做）抵消
- 没法用 14/15 来证明 B 路在 NULL 上的可见性扩展 —— 测试样本已被抹平

### 暂停

零代码 / 零 schema / 零 DB / 零 commit / 零 stash 改动。等顾问决择处置方向。

---

## 【轮次 3 · 2026-05-18 14:30】v2_5_b 第二处 backfill recon

### Q1 — v2_5_b.py 整体结构 + 第 8 步在事务中的角色

`async def migrate()` 在单 transaction (`async with engine.begin() as conn`) 内做 9 步（行号原文）：

| Step | 行 | 作用 | idempotency |
|---|---|---|---|
| 1 | 38-46 | CREATE TABLE IF NOT EXISTS characters | ✅ |
| 2 | 48-58 | CREATE TABLE IF NOT EXISTS conversations | ✅ |
| 3 | 60-62 | ALTER chat_history ADD conversation_id, character_id（duplicate-column 吞）| ✅ |
| 4 | 64-65 | ALTER memory ADD character_id | ✅ |
| 5 | 67-69 | ALTER users ADD nickname, language | ✅ |
| 6 | 71-88 | INSERT default Momo character if 不存在 → 取出 `char_id`（即 Momo 的 id）| ✅（if-exists guard）|
| 7 | 90-106 | 每个 user 若无 conversation 则 INSERT '默认对话' | ✅（per-user if-exists）|
| **8** | **108-134** | **backfill character_id / conversation_id**（含 chat_history.character_id / memory.character_id / chat_history.conversation_id 三个 UPDATE）| ⚠️ 自然 idempotent：UPDATE WHERE IS NULL 跑过一次后无 NULL → 二次 rowcount=0；**但首次发生即不可逆**（NULL→Momo 改写后取不回）|
| 9 | 136-157 | 备份并 DROP TABLE personality | ✅ |

**模块 docstring**："Idempotent — safe to run repeatedly"——基于每条语句自带 guard。**全模块无 schema_version 表 / 无 marker 文件 / 无任何"跑过就 skip"的全局 guard，每次启动无条件重跑 9 步**。

**删 8a (chat_history UPDATE) + 8b (memory UPDATE) 对其它部分影响**：
- 事务结构：单 transaction，删两条 UPDATE 不破事务边界
- `char_id` 变量在 Step 6/7/8 都用；Step 7（INSERT conversation）独立用 char_id，不依赖 Step 8 的两 UPDATE；Step 8c 的 conv_id 循环用 `conv_row` 从 conversations 查（依赖 Step 7 已建好），与 Step 8a/8b 无依赖
- 删 8a/8b 不影响 Step 7、Step 8c、Step 9

### Q2 — memory UPDATE 删除安全性

`v2_5_b.py:113-115` 的 UPDATE：
```python
await conn.execute(
    text("UPDATE memory SET character_id = :cid WHERE character_id IS NULL"),
    {"cid": char_id},   # char_id = Momo's id (1)
)
```

vs B 路改动 3 已删的 main.py V2.5-C2c：
```python
text("UPDATE memory SET character_id = :cid WHERE character_id IS NULL"),
{"cid": momo_id},
```

两者**SQL 完全相同、目标列相同、值来源相同（Momo id）、WHERE 相同**。

**结论**：与已经顾问核准的第一处删除（main.py V2.5-C2c）**完全同语义、同安全性**。删 8b 是已核准方向的自然延伸，无新增风险。

### Q3 — chat_history.character_id 消费者扫描（关键，不盲删）

`grep ChatHistory.character_id` 全代码库出 3 个消费者：

**消费者 1 — `main.py:411-456` 短期记忆窗口启动恢复**
```python
char_id_rows = (await session.execute(
    _select(_distinct(_ChatHistory.character_id))
    .where(_ChatHistory.user_id == default_uid)
)).all()
char_ids = [r[0] for r in char_id_rows]
for cid in char_ids:
    rows = ... .where(_ChatHistory.character_id.is_(cid) if cid is None
                      else _ChatHistory.character_id == cid)
    ...
    await short_term_memory.add(default_uid, msg.role, cleaned,
                                character_id=cid, conversation_id=msg.conversation_id)
```
**显式区分 NULL 与具体 cid**：NULL 行被 `is_(None)` 匹配，加入 `short_term_memory` 的 `character_id=None` bucket。**NULL = 自己一个独立 bucket**，**不与 Momo 合并**。

**消费者 2 — `memory/summary.py:339, 353, 429` fold worker / fold_summaries_for_user**
```python
.where(ChatHistory.character_id.is_(character_id) if character_id is None
       else ChatHistory.character_id == character_id)
```
```sql
SELECT DISTINCT character_id, conversation_id FROM chat_history WHERE user_id = :u
```
**同样显式区分 NULL**：fold 工人按 distinct (cid, conv_id) 跑 → (NULL, conv_id) 形成独立 fold bucket。

**消费者 3 — `proactive/engine.py:163-184` _resolve_target_character_id**
```python
select(ChatHistory.character_id)
    .where(ChatHistory.user_id == user_id)
    .where(ChatHistory.role == "user")
    .where(ChatHistory.character_id.isnot(None))   # ← 显式排除 NULL
    .order_by(ChatHistory.created_at.desc())
    .limit(1)
```
**显式 `isnot(None)` 排除 NULL**——proactive 三档解析跳过 NULL，找最近的具体 character；NULL 行被有意忽略。

### Q3 — 现状实测

```
SELECT COUNT(*) FROM chat_history WHERE character_id IS NULL;  →  0
SELECT character_id, COUNT(*) FROM chat_history GROUP BY character_id;  →  1 | 15
```

**当前 DB 中 chat_history 0 个 NULL 行**——v2_5_b 的 chat_history UPDATE 当前是 no-op（首次启动后无 NULL 可抹）。所有 INSERT 路径（services.add_chat_history 经由 routes/ws.py 与 proactive/engine.py）都传 character_id。

### Q3 — 结论

**选项 (b)：语义不同 / 必须保留 chat_history 那行 UPDATE，只删 memory 那行。**

证据：
- chat_history.character_id 的三个消费者**全部明确区分 NULL 与具体 cid**——把 NULL 视为"自己一个 bucket"或"有意跳过"，**没有把 NULL 视为'跨角色共享'**的语义
- 这与 memory.character_id 的 B 路语义（NULL = 共享）**根本不同**
- 现状无 chat_history NULL 行，UPDATE 是无害 no-op；保留 = 给 legacy 首次启动留兜底，删 = 零收益（chat_history 已无可抹平对象）
- chat_history 所有现行写入路径都传 character_id → 未来也不会再产生 NULL 行；UPDATE 实质退役状态，留之不害

辅助论据：若强行用 B 路语义改 chat_history 读端（NULL = 共享）则需要同步动 3 个消费者，其中 `_resolve_target_character_id` 的 `isnot(None)` 是显式设计意图——属"改了反而引入新问题"的路径。

### Q4 — 全库第三处抹平点扫描

```
4.1 raw SQL UPDATE memory.character_id:
    backend/database/migrations/v2_5_b.py:114                  ← 待删（B 路漏点）
    （main.py V2.5-C2c 已删，不在结果中）

4.2 raw SQL UPDATE chat_history.character_id:
    backend/database/migrations/v2_5_b.py:110                  ← 保留（Q3 决议）

4.3 ORM Memory.character_id = 赋值（任何写入路径）:
    backend/database/services.py:137  ← 这是 B 路改动 1 引入的 or_() 包装的左侧，read-side 不是 write-side
    backend/agents/chat.py:847        ← 同上 read-side
    （无其他 write-side ORM 赋值）

4.4 update().values 或 .update(character_id=...) 模式:
    （空，无任何匹配）

4.5 lifespan / startup hooks:
    backend/main.py:215  async def lifespan  ← 唯一 lifespan，已审计完
    （其它都是文档/注释引用 lifespan 字面，非 hook）
```

**结论**：除已删的 main.py V2.5-C2c + 待删的 v2_5_b.py:113-115 外，**全库无第三处 memory.character_id 抹平点**。

### Q5 — NULL 测试样本恢复方案（只列方案，不执行）

当前 memory id=14/15 已被 v2_5_b 抹平为 cid=1，B 路 `or_()` 的"IS NULL"分支无样本可激活验证。

| 方案 | 操作 | 风险 | 可逆性 |
|---|---|---|---|
| **A** | 从 `momoos.db.backup_bpath_20260518_113501`（11:35 备份，14/15 仍 NULL）attach 后 `UPDATE memory SET character_id=NULL WHERE id IN (14,15)`（参照备份内容确认无误后做） | DB 写动作（1 行变 NULL）；非破坏性，行内容不变 | ⭕ 完全可逆（再 UPDATE 回 1） |
| **B** | 直接 `UPDATE memory SET character_id=NULL WHERE id IN (14,15)` | DB 写动作；与 A 实际等效但不读备份 | ⭕ 完全可逆 |
| **C** | 让用户发一条新 casual 偏好（如"我喜欢狗"）→ extractor 写新 NULL memory 行（id=16+）| 全链路真机回归；但 backend 必须启动、chat_history 会多 1-2 行、memory 多至少 1 行；牵动多模块 | ⚠️ 半可逆（新增的 chat_history+memory 行可 DELETE 但需小心墓碑表是否写入） |
| **D** | 不恢复 NULL 样本；只验"v2_5_b 删 8b 后再启动，14/15 仍是 1（无 NULL 不被抹平显然成立）"——退而求其次只验"抹平点不再生效"的 negative test | 零 DB 改动；放弃 B 路 read-side `OR NULL` 分支的 positive 验证 | N/A（不动数据）|

**推荐预设**（顾问拍板）：
- B 最简、最确定，1 行 SQL，可逆，无副作用
- A 与 B 等效但多读一次备份做交叉确认
- C 真机回归最完整但副作用多
- D 最保守但失去正向证据

**本步不执行任何方案**——等顾问决择 A/B/C/D 后随第二步实施 prompt 一并下达。

### 暂停

零代码改动 / 零 schema / 零 DB / 零 commit / 零 push / 零 stash / 零 backend 启动。
本节真值已 append 至本文件，等顾问核验后再出第二步实施 prompt（含 v2_5_b 删除 + NULL 样本恢复方案）。

---

## 【轮次 4 · 2026-05-18 17:42】v2_5_b 8b 删除 + NULL 样本恢复（方案 A）

### 断电恢复前置自检

- `git status --porcelain`：仅 `chat.py` / `services.py` / `main.py` 三个 M + 既有豁免件（`config.yaml` M + splash-art + 备份）——无断电产生意外改动
- `git stash list` → `stash@{0}: On main: park: 个人config+调试桩(memsum刀前)` 仍在、未动
- `memory` default 用户 14/15 当前 `character_id=1`（断电前未执行恢复，无中间态）
- 断电期间无任何写入

### 本步新备份

```
-rw-r--r--  1 liujunhong  staff  700416  5月 18 17:41
  /Users/liujunhong/Desktop/MomoOS-v2/momoos.db.backup_v25b_20260518_174109
```
700 416 B，与原 DB 等大。

### 交叉确认备份完好

```
-rw-r--r--  1 liujunhong  staff  700416  5月 18 11:35
  momoos.db.backup_bpath_20260518_113501
```
方案 A 的 NULL 来源备份仍在。

### 动作 1 — 删 v2_5_b.py 8b（仅 memory UPDATE 4 行）

`git diff backend/database/migrations/v2_5_b.py`：

```diff
diff --git a/backend/database/migrations/v2_5_b.py b/backend/database/migrations/v2_5_b.py
index 196bb64..da6e183 100644
--- a/backend/database/migrations/v2_5_b.py
+++ b/backend/database/migrations/v2_5_b.py
@@ -110,10 +110,6 @@ async def migrate() -> None:
             text("UPDATE chat_history SET character_id = :cid WHERE character_id IS NULL"),
             {"cid": char_id},
         )
-        await conn.execute(
-            text("UPDATE memory SET character_id = :cid WHERE character_id IS NULL"),
-            {"cid": char_id},
-        )
         for (uid,) in users:
             conv_row = (await conn.execute(
                 text(
```

确认：
- 仅删 4 行（8b 整块：`await conn.execute(` ... `)`）
- 8a（`UPDATE chat_history SET character_id`，L109-112）完整保留，未动
- 8c（`for (uid,) in users:` 起的 `UPDATE chat_history SET conversation_id` 循环，L113+→修后 L109+）完整保留，未动
- Step 7（seed conversation）、Step 9（personality drop）、整个 `async def migrate()` 事务边界 `async with engine.begin() as conn` 未触
- 模块 docstring、其它 import、`_add_column_if_missing` 帮助函数全部未动

### 动作 2 — 方案 A：恢复 14/15 NULL 样本

**Step 2.1 交叉确认备份内容**（只读）：

```
sqlite3 momoos.db.backup_bpath_20260518_113501 \
  "SELECT id,character_id,type,substr(content,1,30) FROM memory
   WHERE id IN (14,15) AND user_id='default'"

14||fact|用户在上海的事业编进入面试阶段
15||instruction|用户喜欢三花猫
```

中间 `||` 之间为空 = `character_id IS NULL`，与轮次 1 备份记录一致。

**Step 2.2 执行 UPDATE**（当前 DB）：

```
UPDATE memory SET character_id=NULL WHERE id IN (14,15) AND user_id='default';
→ changes() = 2
```

**Step 2.3 验证执行后状态**：

```
SELECT id,character_id,type,content FROM memory WHERE id IN (14,15) AND user_id='default';

14||fact|用户在上海的事业编进入面试阶段
15||instruction|用户喜欢三花猫
```

14/15 `character_id` 列均显示为空 = NULL，预期达成。

### Sanity 真值（全表无副作用证明）

```
SELECT COUNT(*) AS total,
       SUM(CASE WHEN character_id IS NULL THEN 1 ELSE 0 END) AS null_cid
FROM memory;
→ 11 | 2     (11 行总数，2 行 NULL，恰好是 14/15)

SELECT COUNT(*) FROM chat_history WHERE character_id IS NULL;
→ 0           (chat_history 未触，8a 行为不变)
```

→ 整个 DB 仅 `memory` 表的 14/15 两行变更，其它行/其它表零副作用。

### `git status --porcelain`（M 类条目）

```
 M backend/agents/chat.py            ← 轮次 1 既有
 M backend/database/migrations/v2_5_b.py   ← 本轮新增 M（动作 1）
 M backend/database/services.py      ← 轮次 1 既有
 M backend/main.py                   ← 轮次 1 既有
 M config.yaml                       ← 既有豁免件，未动
```

B 路相关 M 共 4 个（chat.py / services.py / main.py / v2_5_b.py），符合"轮次 4 后新增 M 只多 v2_5_b.py 一个"。config.yaml 为豁免件。

### 静态自查

| 检查项 | 结果 |
|---|---|
| 8a (`UPDATE chat_history SET character_id`) 完整保留 | ✅ diff 中无 8a 行变动 |
| 8c (`for (uid,) in users:` + `UPDATE chat_history SET conversation_id` 循环) 完整保留 | ✅ diff 中 `for (uid,) in users:` 显示为 context 行（未变） |
| 仅删 8b 一处 memory UPDATE | ✅ diff 仅 4 行 `-`，0 行 `+` |
| `migrate()` 事务结构 (`async with engine.begin()`) 完整 | ✅ 未触 |
| Step 7 / Step 9 / docstring / import / `_add_column_if_missing` | ✅ 全部未动 |
| DB 改动仅 14/15 两行变 NULL | ✅ `SELECT changes() = 2`，全表 NULL 计数 = 2 |
| chat_history NULL 计数不变 | ✅ 0（未触） |
| 其它表 / 其它 memory 行 | ✅ 未触 |

### 当前 B 路落实状态

| 抹平点 | 状态 |
|---|---|
| main.py V2.5-C2c（lifespan 启动 backfill） | ✅ 轮次 1 已删 |
| v2_5_b.py 8b（migrate_v2_5_b memory backfill） | ✅ **本轮已删** |
| 全库第三处 | ❌ 不存在（轮次 3 Q4 已扫） |
| 读端 `or_(cid==N, cid.is_(None))` | ✅ 轮次 1 在 services.py / chat.py 双路落地 |
| NULL 测试样本（id=14/15） | ✅ **本轮恢复完成**（2 行 NULL） |

→ 至此 B 路两处 backfill 全清 + 有 NULL 样本可激活 `OR NULL` 分支正向验证，**可进入真机回归**。

### 暂停

零 commit / 零 push / 零 stash 动作 / 零 backend 启动 / 零 schema 改动 / 零其它代码改动 / 零其它 DB 行改动。等顾问核 diff + DB 真值后发最终真机回归 prompt。

---

## 【轮次 5 · 2026-05-18 23:41】Problem B 最终真机回归 · 闭合步

### 前置自检

- `git status --porcelain` M 类：`chat.py` / `services.py` / `main.py` / `v2_5_b.py` 四个 B 路 M + `config.yaml` 既有豁免 = 5 M ✅
- `stash@{0}: On main: park: 个人config+调试桩(memsum刀前)` 未动 ✅
- 14/15 当前 `character_id` 列空（NULL，轮次 4 恢复态）✅
- 新保险备份：`momoos.db.backup_bpath_final_20260518_174633`（700 416 B）✅
- 交叉备份 `momoos.db.backup_bpath_20260518_113501` 仍在 ✅

### 第 1 步 — 启动 backend（run 1）

启动方式：`uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info`，stdout→`/tmp/momoos_backend_run1.log`。10 s 内 `Application startup complete`。

**启动日志关键证据**：

```
$ grep -nE "V2\.5-C2c|Backfilled.*legacy|UPDATE memory SET character_id" /tmp/momoos_backend_run1.log
(空 — 0 行)

$ grep "V2.5-B migration done" /tmp/momoos_backend_run1.log
7: backend.database.migrations.v2_5_b INFO V2.5-B migration done
```

- 零 `V2.5-C2c` 痕迹（main.py backfill 已删，无 log）
- 零 `Backfilled %d legacy memory rows` 痕迹（轮次 1 删除生效）
- 零 raw SQL `UPDATE memory SET character_id` log（v2_5_b 8b 已删）
- `migrate_v2_5_b` 仍跑（`V2.5-B migration done`），但其内不再含 memory backfill —— 符合轮次 4 删 8b 的预期

启动 banner 节录（migration 链按序跑通）：
```
V2.5-B migration done
V3-B / V3-F / V3-E1 / V3-E1-Z.2 / V3-E2 / V3-E2 yae / V3-E2 momo / V3-G' / V3-G-chunk2 / V3-G-chunk2.6 / V3-G-chunk3 / V3-G-chunk4 / V3.5-chunk5a / V4-fan-chunk1 ... 全 OK
```

embedding/whisper 预加载报 `LocalEntryNotFoundError`（HF 离线缓存缺）—— 与本案无关，**与 memory backfill 无任何关系**，pre-existing 环境问题。

**启动后 14/15 真值**：
```
14||fact|用户在上海的事业编进入面试阶段
15||instruction|用户喜欢三花猫
```
`character_id` 列**仍为 NULL** ✅ —— 两处 backfill 均已根除，启动不再抹平。

→ **第 1 步 PASS**：启动后 14/15 仍 NULL（关键证据：无任何 backfill 痕迹 + DB 真值未变）。

### 第 2 步 — 三路可见性实测（cid=1 视角）

**UI 路 — `GET /api/memory/list?user_id=default&character_id=1`**

```
$ curl http://127.0.0.1:8000/api/memory/list?user_id=default&character_id=1
count= 2
14 None fact 用户在上海的事业编进入面试阶段
15 None instruction 用户喜欢三花猫
```
2 行 NULL 行被 `OR NULL` 命中 ✅（不是因为它们 cid=1，是因为 services.py 改动 1 的 `or_(==N, IS NULL)`）。

**LLM tool 路 — `_tool_list_memories(user='default', cid=1)` 等价调用**

```
=== list_memories(cid=1) ===
count= 2
14 fact 用户在上海的事业编进入面试阶段
15 instruction 用户喜欢三花猫
```
同样 2 行 ✅（走 services.get_all_memories，B 路 OR NULL 命中）。

**wake_call 路 — `aggregate_briefing_data(user='default', cid=1)` 等价调用**

（注：proactive/engine.py 实际函数名是 `aggregate_briefing_data`，wake_call 在 stage1 调它；prompt 中"aggregate_for_wake_call"是别名表达。该函数在 L693-704 走 `get_all_memories(cid=cid)` + 过滤 `m.type=='instruction'`。）

```
=== aggregate_briefing_data(cid=1) instruction_memories ===
count= 1
15 instruction 用户喜欢三花猫
```
1 行 ✅（id=15 type=instruction，命中；id=14 type=fact，被函数自身的 `if m.type == "instruction"` 过滤，符合既有实现意图）。

→ **第 2 步 PASS**：三路全从轮次 1 改前的"0 行"变为"2/2/1 行"，B 路 `OR NULL` 分支真正激活。

### 第 3 步 — 重启一致性（连续两次）

**Run 2**（stop run1 → 启动 run2）：
```
$ grep -nE "V2\.5-C2c|Backfilled.*legacy|UPDATE memory SET character_id" /tmp/momoos_backend_run2.log
(空)
$ grep "V2.5-B migration done" /tmp/momoos_backend_run2.log
7: backend.database.migrations.v2_5_b INFO V2.5-B migration done
$ SELECT id,character_id FROM memory WHERE id IN (14,15)
14|<NULL>|fact|用户在上海的事业编进入面试阶段
15|<NULL>|instruction|用户喜欢三花猫
```

**Run 3**（stop run2 → 启动 run3）：
```
$ grep ... (同上，空)
$ grep "V2.5-B migration done" /tmp/momoos_backend_run3.log
7: backend.database.migrations.v2_5_b INFO V2.5-B migration done
$ SELECT id,character_id FROM memory WHERE id IN (14,15)
14|<NULL>|fact|用户在上海的事业编进入面试阶段
15|<NULL>|instruction|用户喜欢三花猫
```

总共 3 次启动（run1/run2/run3），14/15 全程 `character_id IS NULL` 未被抹平。

→ **第 3 步 PASS**：两处 backfill 真根除，无隐藏第 3 处抹平。

### 第 4 步 — 不带过滤路径回归

`chat.py:1167` 与 `chat.py:1420` 两处都调 `search_relevant_memories(user_id, query=text, top_k=5)` —— **不传 character_id**。底层走 `get_all_memories(session, user_id, character_id=None)`。

**底层 get_all_memories(cid=None) 等价调用**：
```
=== get_all_memories(default, cid=None) ===
count= 2
14 None fact 用户在上海的事业编进入面试阶段
15 None instruction 用户喜欢三花猫
```
2 行 ✅ —— B 路改动 1 的 `if character_id is not None:` 守门，character_id=None 时 `or_()` 分支**完全不进入**，等同 B 路改前行为。

**真·semantic recall 全链路**（query 长度需 ≥ config.embedding.short_input_threshold=10）：
```
query='告诉我用户最近的事业进展和宠物偏好情况' (len=19)
→ count=1, returns id=15 (NULL row)

query='用户对工作和宠物有什么偏好' (len=13)
→ count=1, returns id=15 (NULL row)
```
NULL 行可被 cosine 检索召回 ✅ —— recall 路径不仅"未被 B 路改坏"，且 NULL 行本身**就是召回候选**，downstream cosine + forgetting curve 才决定 top_k 取哪一行（id=15 而非 14 是 cosine/forgetting 自然结果，非 B 路相关）。

（短 query `"三花猫"` len=3<10 直接被 short_input_gate 返 `[]` —— 是 config 设计，与 B 路无关。）

→ **第 4 步 PASS**：不带过滤路径 recall 仍正常工作；B 路 `or_()` 分支在 character_id=None 时 dormant，无侵入；NULL 行进入 recall 候选池，行为未因 B 路改坏。

### 第 5 步 — 闭合判定

| # | 检查项 | 实测 | 结果 |
|---|---|---|---|
| ① | 启动后 14/15 仍 NULL（启动日志零 backfill 痕迹） | 3 次启动全 NULL；零 V2.5-C2c / 零 Backfilled / 零 UPDATE memory log | **PASS** |
| ② | 三路（UI / list_memories / wake_call）均从 0 变 2/2/1 | UI=2 / list_memories=2 / wake_call instruction=1（type 过滤后） | **PASS** |
| ③ | 连续两次重启 14/15 仍 NULL | run1/run2/run3 三次启动全 NULL | **PASS** |
| ④ | 不带过滤 recall 路径无误伤 | get_all_memories(cid=None)=2；search_relevant_memories 长 query → 召回 id=15 NULL 行 | **PASS** |

**全 4 项 PASS → Problem B 闭合**。

### 闭合后状态对账

| 项 | 改前（轮次 0 baseline） | 改后（轮次 5 闭合） |
|---|---|---|
| main.py V2.5-C2c backfill | 存在，启动抹 NULL→1 | ❌ 已删（轮次 1） |
| v2_5_b.py 8b memory backfill | 存在，启动抹 NULL→1 | ❌ 已删（轮次 4） |
| services.py read 过滤 | `Memory.character_id == cid` 严格 | ✅ `or_(== cid, IS NULL)`（轮次 1） |
| chat.py compress_memories fetch | `Memory.character_id == cid` 严格 | ✅ `or_(== cid, IS NULL)`（轮次 1） |
| chat.py top import or_ | 缺 | ✅ 已补（轮次 1） |
| memory 14/15 NULL 样本 | 启动后被抹为 1 | ✅ 真 NULL，持久不被抹平（轮次 4 恢复 + 轮次 5 验证 3 次启动持久） |
| cid=1 视角下 14/15 可见性 | 0 行 | ✅ UI 2 / list_memories 2 / wake_call.instruction 1 |
| 不带过滤 recall 受影响 | — | ✅ 未受影响（or_ 分支 dormant when cid=None） |
| chat_history.character_id 抹平点 | v2_5_b 8a 保留（语义不同，轮次 3 决议保留） | ✅ 保留，未触 |

### 状态

- backend 进程已全部停止（最终 `pgrep -f "uvicorn backend.main"` 空）
- 当前 `git status --porcelain | grep M` 5 条不变：4 个 B 路 M + 1 个豁免件 `config.yaml`
- 14/15 当前持久 NULL（DB 真值）
- 零 commit / 零 push / 零 stash 动作 / 零代码改动 / 零 schema 改动 / 零手动 DB 行改动

### 最终结论

**Problem B 闭合**。两处 memory.character_id backfill 全清；读端 OR NULL 共享语义在 services.py 与 chat.py 双路落地；NULL 样本（id=14/15）可在 cid=1 视角下被三路读端命中、在不带过滤路径下被 recall 召回；3 次重启验证抹平点根除，无隐藏第 N 处；不带过滤路径无误伤。

下一步由顾问决定是否 commit + 处理 stash。本档案不 commit。

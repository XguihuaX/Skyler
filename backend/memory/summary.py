"""有界滚动摘要层(v4-beta Stage 2 第一刀).

# 设计

audit_z5(Stage 1)+ /tmp/diag_z5_report.md(Stage 2 第一刀)双证:
- LLM-driven fact extraction(``backend/memory/extractor.py``)对默认用户 0 行
- 真因不是 bug 是 policy:LLM 按 prompt 主动判定短 / 稀 chat_history 无 fact 可记
  → ``[]`` → 0 写入
- short_term ``cap30`` 挤掉旧 turn 后,这些 turn 永远进不了 long-term 沉淀
- 30 轮后用户体感"完全失忆"

本模块**新加一层**:旧 turn 被 cap 挤出窗口时,**有界重压缩**(非 append)
进单个 ``summary_text`` 字段。

# 关键不变量

1. **范围**:``(user_id, character_id, conversation_id)`` 三级隔离
   - 与 ``eeb427a`` Bug 1 修法(short_term per-conv 过滤)对齐
   - 与现有 ``delete_conversation`` 硬删语义对齐(summary 随 conv 走)
   - **不会**让"新对话=清白起点"被打破
2. **独立状态**:本模块的 ``last_folded_chat_history_id`` 在 ``conversation_summary``
   表自己一列里,**完全不读/不写** ``memory_extractor_state``。后者 pointer 对
   default 用户卡死在 804(audit 实测),搭车会一起卡死。
3. **触发**:被动 — 已存在的 ``MemoryExtractor`` worker 在 ``_extract_batch`` 末尾
   额外为每个用户调一次 ``fold_summaries_for_user``。不创建第二个 worker 任务。
   interval 复用 extractor 的 ``interval_seconds``(默认 300s),不另起节流。
4. **批量**:一次 fold 只处理"被 cap 挤出窗口的最早一批 turn"(``SUMMARY_BATCH_TURNS``,
   默认 10)。挤出更多?下一 tick 接着 fold。不在单 tick 内追平所有积压(防卡顿)。
5. **更新 = 重压缩**:取 ``(当前 summary_text + 新挤出的 batch)`` 喂 ``summary_model``,
   产出新摘要**重新压回 token_budget 以内**。**不是 append**。
6. **失败可见**:LLM 调用失败 → ``logger.error`` 打醒目日志(不静默 swallow),
   **不**更新 ``last_folded_chat_history_id``(等下个 tick 重试)。不崩 worker。
7. **空摘要不注入**:首批 fold 之前(短对话期)``summary_text=''``,injection 处
   if-guard 跳过,零成本零干扰。
8. **不复用主聊天 model**:``summary_model`` 从 config.yaml 拿,独立于
   ``default_model`` / ``planner_model``。
9. **触发门控**:chat_history 总数 ≤ ``SHORT_TERM_MAX``(60)时不 fold(此时所有 turn
   仍在 short_term 窗口,无东西挤出)。> 60 时 fold "id 比 ``last_folded`` 大且仍在
   cap 之外" 的最早一批。

# Public API

- ``get_summary(user_id, character_id, conversation_id) -> Optional[str]`` — 注入侧读
- ``fold_summaries_for_user(user_id)`` — worker 侧调
- ``fold_one_key(user_id, character_id, conversation_id)`` — 单 key 直接调(测试用)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text

from backend.config import config_yaml
from backend.database import AsyncSessionLocal, engine
from backend.database.models import ChatHistory
from backend.llm.client import LLMError, call_llm
from backend.memory.short_term import SHORT_TERM_MAX

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------


def _summary_cfg() -> dict:
    return ((config_yaml.get("memory") or {}).get("summary") or {})


def get_summary_enabled() -> bool:
    """总开关。False → fold 静默跳过、get_summary 返 None。"""
    return bool(_summary_cfg().get("enabled", True))


def get_summary_model() -> str:
    """独立 model 字符串(litellm 格式 ``provider/model``)。**不复用主聊天 model**。

    默认 ``openai/qwen3.5-flash``(用户指定 Qwen3.5-Flash);若 LiteLLM 上不识别
    这个 model 名 → ``call_llm`` 抛 ``LLMError`` → 我们的 ``except`` 分支
    log + skip,**不静默吞,不污染状态**。Ernestmk 可在 config 改成具体可用串。
    """
    return str(_summary_cfg().get("model", "openai/qwen3.5-flash"))


def get_summary_token_budget() -> int:
    """单 conv 摘要的 token 上限(初始化 ``token_budget`` 列用)。默认 1000。"""
    try:
        return int(_summary_cfg().get("token_budget", 1000))
    except (TypeError, ValueError):
        return 1000


def get_summary_batch_turns() -> int:
    """单 tick 最多 fold 多少 turn(挤出窗口的最早一批)。默认 10。"""
    try:
        return int(_summary_cfg().get("batch_turns", 10))
    except (TypeError, ValueError):
        return 10


def get_summary_min_batch() -> int:
    """挤出窗口的 turn 数 < 该值时不触发 fold(降抖动)。默认 4。"""
    try:
        return int(_summary_cfg().get("min_batch", 4))
    except (TypeError, ValueError):
        return 4


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------


def _build_fold_prompt(
    existing_summary: str,
    batch_turns: list,
    token_budget: int,
) -> str:
    """组装重压缩 prompt。

    Args:
        existing_summary: 当前 summary_text(可能为 '')
        batch_turns: 本批要折进来的 chat_history 行(user / assistant 均含)
        token_budget: 输出摘要的 token 预算上限

    Returns:
        ready-for ``call_llm`` 的 prompt string
    """
    turns_block: list[str] = []
    for t in batch_turns:
        role_zh = "用户" if t.role == "user" else "她"
        content = (t.content or "").strip()
        if not content:
            continue
        turns_block.append(f"[{role_zh}] {content}")
    turns_text = "\n".join(turns_block) if turns_block else "(空)"

    existing_block = (
        existing_summary.strip()
        if existing_summary and existing_summary.strip()
        else "(尚无)"
    )

    return f"""任务:把"现有摘要"和"新挤出窗口的对话片段"合并,**重新压缩**成
一段不超过 {token_budget} token 的新摘要。这是滚动摘要,会覆盖现有摘要,
所以**不许 append**,**必须重压缩**。

保留(高显著度):
- 用户与她的关系演变(称呼变化 / 亲密度变化 / 信任建立的具体时刻)
- 用户当下的情绪状态(哪里累 / 哪里开心 / 在烦什么)
- 用户做过的承诺 / 计划 / 立的 flag
- 用户多次提及的偏好与习惯模式
- 她回应用户时的角色亮点(她如何安慰 / 拒绝 / 开玩笑)

丢弃 / 压糊(低显著度):
- 已不再相关的过往话题细节
- 单次寒暄、单次问候、单次时间感叹
- 同质化重复内容(只留一次,标"多次")
- 工具调用过程的细枝末节

输出规则:
1. **纯叙事段落**,中文,自然流畅(不要 JSON,不要 bullet list)。
2. 称用户为"用户",称她为"她"(避免代入名字,角色身份由 persona 注入)。
3. 长度严格 ≤ {token_budget} token(中文约 {token_budget * 3 // 2} 字)。
4. 若现有摘要+新片段加起来本就无可记之事 → 输出 ``(无显著进展)``;
   读侧会跳过注入。

现有摘要:
{existing_block}

新挤出窗口的对话片段(按时间升序):
{turns_text}"""


# ---------------------------------------------------------------------------
# LLM caller(可见失败 — 不静默吞)
# ---------------------------------------------------------------------------


async def _call_summary_llm(prompt: str) -> Optional[str]:
    """调 summary_model 拿压缩后的摘要。

    失败 → 返 ``None`` + **error 级 log**(不是 warning),让运维真能看到。
    上层不会推进 ``last_folded_chat_history_id``,下一 tick 自然重试。
    """
    model = get_summary_model()
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            logger.error(
                "[summary] LLM returned empty content model=%s prompt_chars=%d",
                model, len(prompt),
            )
            return None
        return raw
    except LLMError as exc:
        logger.error(
            "[summary] LLM call failed model=%s err=%s "
            "— skipping this batch, pointer NOT advanced",
            model, exc,
        )
        return None
    except Exception as exc:
        logger.error(
            "[summary] unexpected LLM error model=%s err=%s "
            "— skipping this batch, pointer NOT advanced",
            model, exc,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Public read API(injection side)
# ---------------------------------------------------------------------------


async def get_summary(
    user_id: str,
    character_id: Optional[int],
    conversation_id: Optional[int],
) -> Optional[str]:
    """读 (user, char, conv) 的 summary_text。空 / 无行 → 返 None。

    chat.py::_build_messages 在 short_term 注入前调本函数,有则插独立 system 块,
    空则跳过(零成本)。
    """
    if not get_summary_enabled():
        return None
    try:
        async with engine.begin() as conn:
            row = (await conn.execute(text(
                "SELECT summary_text FROM conversation_summary "
                "WHERE user_id = :u AND character_id IS :c "
                "  AND conversation_id IS :v"
            ), {"u": user_id, "c": character_id, "v": conversation_id})).fetchone()
        if row is None:
            return None
        s = (row[0] or "").strip()
        if not s or s == "(无显著进展)":
            return None
        return s
    except Exception:
        logger.exception(
            "[summary] get_summary failed user=%s char=%s conv=%s",
            user_id, character_id, conversation_id,
        )
        return None


# ---------------------------------------------------------------------------
# Per-key folder(worker 调)
# ---------------------------------------------------------------------------


async def _get_or_create_state(
    user_id: str,
    character_id: Optional[int],
    conversation_id: Optional[int],
) -> tuple[str, int, int]:
    """读 / 初始化 (user, char, conv) 行,返 (summary_text, last_folded_id, token_budget)。"""
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT summary_text, last_folded_chat_history_id, token_budget "
            "FROM conversation_summary "
            "WHERE user_id = :u AND character_id IS :c AND conversation_id IS :v"
        ), {"u": user_id, "c": character_id, "v": conversation_id})).fetchone()
        if row is not None:
            return (row[0] or "", int(row[1] or 0), int(row[2] or get_summary_token_budget()))
        budget = get_summary_token_budget()
        await conn.execute(text(
            "INSERT INTO conversation_summary "
            "(user_id, character_id, conversation_id, summary_text, "
            " last_folded_chat_history_id, token_budget, updated_at) "
            "VALUES (:u, :c, :v, '', 0, :b, :now)"
        ), {
            "u": user_id, "c": character_id, "v": conversation_id,
            "b": budget, "now": datetime.utcnow(),
        })
    return ("", 0, budget)


async def _write_state(
    user_id: str,
    character_id: Optional[int],
    conversation_id: Optional[int],
    summary_text: str,
    last_folded_id: int,
) -> None:
    """覆盖写 summary_text + last_folded。单事务。"""
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE conversation_summary "
            "SET summary_text = :s, last_folded_chat_history_id = :p, "
            "    updated_at = :now "
            "WHERE user_id = :u AND character_id IS :c "
            "  AND conversation_id IS :v"
        ), {
            "s": summary_text, "p": last_folded_id, "now": datetime.utcnow(),
            "u": user_id, "c": character_id, "v": conversation_id,
        })


async def fold_one_key(
    user_id: str,
    character_id: Optional[int],
    conversation_id: Optional[int],
) -> dict:
    """对一个 (user, char, conv) 跑一次 fold。

    返回 ``{"status": "...", ...}`` 给调用方/测试观察。状态:
      * ``"disabled"``    — 总开关 off
      * ``"no_cap_breach"`` — chat_history 总数 ≤ SHORT_TERM_MAX,无东西挤出
      * ``"too_small"``   — 挤出 batch < min_batch,本 tick 不动
      * ``"llm_failed"``  — LLM 调用失败(log 已 error),pointer 未推进
      * ``"folded"``      — 成功,summary_text + pointer 已更新
    """
    if not get_summary_enabled():
        return {"status": "disabled"}

    summary_text, last_folded, budget = await _get_or_create_state(
        user_id, character_id, conversation_id,
    )

    # 总数 ≤ cap → 无东西挤出 → 不 fold
    async with AsyncSessionLocal() as session:
        total = (await session.execute(
            select(text("COUNT(*)"))
            .select_from(ChatHistory)
            .where(ChatHistory.user_id == user_id)
            .where(ChatHistory.character_id.is_(character_id) if character_id is None
                   else ChatHistory.character_id == character_id)
            .where(ChatHistory.conversation_id.is_(conversation_id) if conversation_id is None
                   else ChatHistory.conversation_id == conversation_id)
        )).scalar() or 0
    if int(total) <= SHORT_TERM_MAX:
        return {"status": "no_cap_breach", "total": int(total)}

    # 找"挤出窗口的最早 batch":id > last_folded 且 id < cap_cutoff_id
    # cap_cutoff_id = 倒数第 SHORT_TERM_MAX 条的 id(它是仍在窗口内的最旧条)
    async with AsyncSessionLocal() as session:
        cap_row = (await session.execute(text(
            "SELECT id FROM chat_history "
            "WHERE user_id = :u "
            f"  AND character_id {'IS NULL' if character_id is None else '= :c'} "
            f"  AND conversation_id {'IS NULL' if conversation_id is None else '= :v'} "
            "ORDER BY id DESC LIMIT 1 OFFSET :off"
        ), {
            "u": user_id,
            **({"c": character_id} if character_id is not None else {}),
            **({"v": conversation_id} if conversation_id is not None else {}),
            "off": SHORT_TERM_MAX - 1,
        })).fetchone()
    if cap_row is None:
        return {"status": "no_cap_breach", "total": int(total)}
    cap_cutoff_id = int(cap_row[0])

    batch_turns_cfg = get_summary_batch_turns()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(
            "SELECT id, role, content, created_at FROM chat_history "
            "WHERE user_id = :u "
            f"  AND character_id {'IS NULL' if character_id is None else '= :c'} "
            f"  AND conversation_id {'IS NULL' if conversation_id is None else '= :v'} "
            "  AND id > :last AND id < :cut "
            "ORDER BY id ASC LIMIT :lim"
        ), {
            "u": user_id,
            **({"c": character_id} if character_id is not None else {}),
            **({"v": conversation_id} if conversation_id is not None else {}),
            "last": last_folded, "cut": cap_cutoff_id, "lim": batch_turns_cfg,
        })).fetchall()
    batch = list(rows)

    if len(batch) < get_summary_min_batch():
        return {"status": "too_small", "batch_len": len(batch)}

    # build + call LLM
    class _RowProxy:
        __slots__ = ("id", "role", "content")
        def __init__(self, id_, role, content):
            self.id = id_; self.role = role; self.content = content
    batch_objs = [_RowProxy(r[0], r[1], r[2]) for r in batch]

    prompt = _build_fold_prompt(summary_text, batch_objs, budget)
    new_summary = await _call_summary_llm(prompt)
    if new_summary is None:
        return {"status": "llm_failed", "batch_len": len(batch)}

    # 写回(单事务:summary + pointer 同时更新)
    last_folded_new = int(batch[-1][0])
    await _write_state(
        user_id, character_id, conversation_id,
        new_summary, last_folded_new,
    )
    logger.info(
        "[summary] folded user=%s char=%s conv=%s batch_len=%d "
        "new_summary_chars=%d last_folded %d → %d",
        user_id, character_id, conversation_id, len(batch),
        len(new_summary), last_folded, last_folded_new,
    )
    return {
        "status": "folded",
        "batch_len": len(batch),
        "new_summary_chars": len(new_summary),
        "new_summary": new_summary,
        "last_folded_was": last_folded,
        "last_folded_now": last_folded_new,
    }


# ---------------------------------------------------------------------------
# Worker entry(extractor._extract_batch 末尾调)
# ---------------------------------------------------------------------------


async def fold_summaries_for_user(user_id: str) -> None:
    """对该用户所有 (char, conv) 跑 fold。worker 每 tick 一次。

    实现:
      1. 从 chat_history 拿该用户出现过的所有 distinct (character_id, conversation_id)
      2. 逐对调 ``fold_one_key``
      3. 任一对失败吞 + log,不阻塞其他对 / worker 主循环
    """
    if not get_summary_enabled():
        return
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT DISTINCT character_id, conversation_id "
                "FROM chat_history WHERE user_id = :u"
            ), {"u": user_id})).fetchall()
    except Exception:
        logger.exception("[summary] list keys failed user=%s", user_id)
        return

    keys = [(r[0], r[1]) for r in rows]
    for char_id, conv_id in keys:
        try:
            result = await fold_one_key(user_id, char_id, conv_id)
            if result.get("status") == "folded":
                logger.debug(
                    "[summary] fold ok user=%s char=%s conv=%s",
                    user_id, char_id, conv_id,
                )
        except Exception:
            logger.exception(
                "[summary] fold_one_key crashed user=%s char=%s conv=%s "
                "— skip, worker continues",
                user_id, char_id, conv_id,
            )


__all__ = [
    "fold_one_key",
    "fold_summaries_for_user",
    "get_summary",
    "get_summary_enabled",
    "get_summary_model",
    "get_summary_token_budget",
    "get_summary_batch_turns",
    "get_summary_min_batch",
]

"""v3.5 chunk 10 — server-side MemoryExtractor worker。

每 N 分钟从 ``chat_history`` 提取 memory entries，跟 chunk 11 cron 相同
精神但用 ``asyncio.create_task`` + ``while True: await sleep`` 模式
（worker 触发频率高，APScheduler 太重）。

工作流（commit 4 完整实现）：

  1. 读 ``last_processed_turn_id`` 之后的 ``role='user' kind='normal'``
     turn（commit 2 实现）
  2. 用 qwen-turbo + 提取 prompt 产出 entries JSON list（commit 3 实现）
  3. validator + quality filter（commit 4 实现）
  4. 通过 filter 的 entries 入 ``memory`` 表 + ``extraction_source='worker'``
     + ``source_turn_id``（commit 4 实现）
  5. 更新 ``last_processed_turn_id`` 为本批最大 turn id（commit 2 实现）

任何子步骤异常吞 + log，不阻塞主对话（worker 失败仅影响"未来 N 分钟没
提取"，用户体感为零）。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text

from backend.config import config_yaml
from backend.database import AsyncSessionLocal, engine
from backend.database.models import ChatHistory, User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------


def _extractor_cfg() -> dict:
    return ((config_yaml.get("memory") or {}).get("extractor") or {})


def get_extractor_enabled() -> bool:
    """chunk 10 worker 总开关。False 时 lifespan 不启动 worker（log 静默）。"""
    return bool(_extractor_cfg().get("enabled", True))


def get_extractor_interval_seconds() -> int:
    """两次 batch 之间 sleep 秒数。默认 300（5 分钟）。"""
    try:
        return int(_extractor_cfg().get("interval_seconds", 300))
    except (TypeError, ValueError):
        return 300


def get_extractor_batch_size() -> int:
    """单批次最多扫多少条新 turn。默认 50。"""
    try:
        return int(_extractor_cfg().get("batch_size", 50))
    except (TypeError, ValueError):
        return 50


def get_extractor_min_confidence() -> float:
    """LLM 自评 confidence < 阈值 → reject。默认 0.5。"""
    try:
        return float(_extractor_cfg().get("min_confidence", 0.5))
    except (TypeError, ValueError):
        return 0.5


def get_extractor_llm_judge_enabled() -> bool:
    """第 5 道 filter：LLM judge "对未来对话有用吗" 默认关。"""
    return bool(_extractor_cfg().get("llm_judge_enabled", False))


def get_extractor_dup_threshold() -> float:
    """重复检测 cosine 相似度阈值。> N 视同重复，reject。默认 0.9。"""
    try:
        return float(_extractor_cfg().get("dup_threshold", 0.9))
    except (TypeError, ValueError):
        return 0.9


# ---------------------------------------------------------------------------
# State table helpers (memory_extractor_state)
# ---------------------------------------------------------------------------


async def get_last_processed_turn_id(user_id: str) -> int:
    """读 user 的 last_processed_turn_id；未注册 user 返 0（从 0 起扫）。"""
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT last_processed_turn_id FROM memory_extractor_state "
            "WHERE user_id = :u"
        ), {"u": user_id})).fetchone()
    return int(row[0]) if row else 0


async def update_last_processed_turn_id(user_id: str, turn_id: int) -> None:
    """upsert ``memory_extractor_state``。

    sqlite ``INSERT ... ON CONFLICT`` 不便async wrap；用先 SELECT 再
    INSERT / UPDATE 走两个 SQL，简单可靠。
    """
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT id FROM memory_extractor_state WHERE user_id = :u"
        ), {"u": user_id})).fetchone()
        now = datetime.utcnow()
        if row is None:
            await conn.execute(text(
                "INSERT INTO memory_extractor_state "
                "(user_id, last_processed_turn_id, updated_at) "
                "VALUES (:u, :t, :w)"
            ), {"u": user_id, "t": int(turn_id), "w": now})
        else:
            await conn.execute(text(
                "UPDATE memory_extractor_state "
                "SET last_processed_turn_id = :t, updated_at = :w "
                "WHERE user_id = :u"
            ), {"u": user_id, "t": int(turn_id), "w": now})


# ---------------------------------------------------------------------------
# Chat history fetcher
# ---------------------------------------------------------------------------


@dataclass
class ChatTurn:
    """轻量结构 —— 不暴露完整 ChatHistory ORM 给 prompt/validator 层。"""
    id: int
    content: str
    created_at: Optional[datetime]


async def fetch_user_turns_after(
    user_id: str,
    after_id: int,
    *,
    batch_size: int,
) -> list[ChatTurn]:
    """拉 ``role='user' kind='normal'`` 且 ``id > after_id`` 的 turn。

    按 ``id`` 升序，最多 ``batch_size``。给 worker 增量扫用。
    """
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(
                ChatHistory.id,
                ChatHistory.content,
                ChatHistory.created_at,
            )
            .where(ChatHistory.user_id == user_id)
            .where(ChatHistory.role == "user")
            .where(ChatHistory.kind == "normal")
            .where(ChatHistory.id > int(after_id))
            .order_by(ChatHistory.id.asc())
            .limit(int(batch_size))
        )).all()
    return [
        ChatTurn(id=r[0], content=r[1] or "", created_at=r[2])
        for r in rows
    ]


# ---------------------------------------------------------------------------
# MemoryExtractor (worker)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Entry save + optional LLM judge
# ---------------------------------------------------------------------------


# entry_type → ``Memory.type`` 五分类约束的映射（chunk 2 ORM CheckConstraint
# 锁死 type ∈ {fact / instruction / emotion / activity / daily}）。worker
# 写入时同时填两列：``type`` 兼容旧 UI 过滤；``entry_type`` 给 chunk 10
# 新 UI 用。
_TYPE_LEGACY_MAP = {
    "fact":       "fact",
    "preference": "instruction",  # 偏好 → 旧 'instruction'（与 chunk 2 习惯一致）
    "event":      "activity",     # 事件 → 旧 'activity'
    "commitment": "activity",     # 承诺 → 旧 'activity'（最贴近"未来安排"）
}


async def _save_worker_entries(
    user_id: str,
    entries: list[dict],
    *,
    source_turn_id: Optional[int],
) -> None:
    """把 worker 通过 filter 的 entries 写入 ``memory`` 表。

    每条 entry 标 ``extraction_source='worker'``。同时填新 5 列
    （chunk 10 schema）+ 老 ``type`` 列（兼容旧过滤 UI）。
    """
    from sqlalchemy import text as sql_text
    from backend.memory.long_term import generate_embedding

    now = datetime.utcnow()
    for entry in entries:
        content = entry["content"]
        entry_type = entry["type"]
        confidence = entry["confidence"]
        legacy_type = _TYPE_LEGACY_MAP.get(entry_type, "fact")

        # embedding（best-effort；失败 → 入库 NULL，后续检索就跳过）
        embedding_blob: Optional[bytes] = None
        try:
            embedding_blob = await generate_embedding(content)
        except Exception:
            logger.warning(
                "[extractor] embedding gen failed; saving with NULL "
                "embedding user=%s content=%r",
                user_id, content[:80],
            )

        async with engine.begin() as conn:
            await conn.execute(sql_text(
                "INSERT INTO memory "
                "(user_id, role, type, content, embedding, "
                " created_at, access_count, last_accessed_at, "
                " extracted_at, source_turn_id, confidence, entry_type, "
                " extraction_source) "
                "VALUES "
                "(:user_id, :role, :type, :content, :embedding, "
                " :created_at, 0, :created_at, "
                " :extracted_at, :source_turn_id, :confidence, :entry_type, "
                " :extraction_source)"
            ), {
                "user_id": user_id,
                "role": "user",  # chunk 2 CHECK 约束 ∈ {user, system}
                "type": legacy_type,
                "content": content,
                "embedding": embedding_blob,
                "created_at": now,
                "extracted_at": now,
                "source_turn_id": source_turn_id,
                "confidence": confidence,
                "entry_type": entry_type,
                "extraction_source": "worker",
            })


def _make_llm_judge():
    """构造第 5 道 filter（可选）：LLM judge "本条 entry 对未来对话有用吗"。

    ``config.memory.extractor.llm_judge_enabled=True`` 才接入。当前实现是
    简单二分判断，未来可加 nuance。
    """
    async def judge(content: str) -> bool:
        from backend.config import get_planner_model
        from backend.llm.client import LLMError, call_llm
        prompt = (
            "判断以下记忆条目**对未来对话**是否有长期价值。\n\n"
            f"条目：{content}\n\n"
            "**只回答** YES 或 NO，不要解释、不要标点。"
        )
        try:
            response = await call_llm(
                messages=[{"role": "user", "content": prompt}],
                model=get_planner_model(),
                stream=False,
            )
            raw = (response.choices[0].message.content or "").strip().upper()
            return raw.startswith("Y")
        except LLMError:
            return True  # fail-open
        except Exception:
            logger.exception("[extractor.llm_judge] unexpected error")
            return True
    return judge


class MemoryExtractor:
    """单实例 worker，每 ``interval`` 秒跑一次 ``_extract_batch``。

    主要方法：
      * ``run_loop()`` —— ``while True`` 入口，由 lifespan
        ``asyncio.create_task`` 拉起
      * ``stop()`` —— 优雅 stop，由 lifespan shutdown 调
      * ``_extract_batch()`` —— 单批工作（commit 4 完整实现 LLM + filter）

    commit 2 的 ``_extract_batch`` 只实现"读 turn / 占位 LLM = no-op /
    更新 state"骨架，不真正写 memory 表。commit 3/4 接 prompt + validator
    + save 完成完整流水线。
    """

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def _list_user_ids(self) -> list[str]:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(User.user_id))).all()
        return [r[0] for r in rows if r[0]]

    async def _extract_batch(self) -> None:
        """单批工作循环（per-user）。commit 2 占位实现；commit 4 真接 LLM。

        v4-beta Stage 2:每个 user 跑完 extractor 后,额外调一次
        ``fold_summaries_for_user``(滚动摘要层)。**完全独立状态**(用
        ``conversation_summary.last_folded_chat_history_id``,不读
        ``memory_extractor_state``)—— 即便 extractor 的 pointer 卡死,summary 也能
        自己往前走。summary 的失败处理在 ``backend/memory/summary.py`` 内自封闭
        (LLM 失败 error log + 不推 pointer,不会冒泡到这里),所以即便 summary 抛
        本 try/except 也兜住,不影响主 worker 循环。
        """
        # 延迟 import 避免 module-load 期循环 import
        from backend.memory.summary import fold_summaries_for_user

        user_ids = await self._list_user_ids()
        batch_size = get_extractor_batch_size()
        total_seen = 0
        for uid in user_ids:
            try:
                last_id = await get_last_processed_turn_id(uid)
                turns = await fetch_user_turns_after(
                    uid, last_id, batch_size=batch_size,
                )
                if turns:
                    total_seen += len(turns)
                    # commit 3/4 这里接 prompt + LLM + validator + save。
                    # commit 2 占位：仅推进 state pointer（让单测能验证流水线
                    # 框架；真 LLM/save 行为留给 commit 4）。
                    await self._process_user_turns(uid, turns)
                    await update_last_processed_turn_id(uid, turns[-1].id)
                # v4-beta Stage 2:无论 extractor 是否处理了新 turn,都跑一次
                # 滚动摘要 fold(summary 状态独立于 extractor pointer,extractor 卡死
                # 也不耽误 summary)。summary 自检 cap_breach / 自校 batch 大小,
                # 没东西要 fold 时静默 return,零成本。
                await fold_summaries_for_user(uid)
            except Exception:
                logger.exception(
                    "[extractor] _extract_batch failed for user=%s", uid,
                )
        logger.debug(
            "[extractor] batch done: %d user(s), %d new turn(s) scanned",
            len(user_ids), total_seen,
        )

    async def _process_user_turns(
        self, user_id: str, turns: list[ChatTurn],
    ) -> None:
        """commit 4 实现：prompt → LLM → validator → save。

        任一子步骤异常都吞 + log，不阻塞 worker loop。
        """
        from backend.prompts.memory_extraction import (
            build_extraction_prompt,
            call_extraction_llm,
        )
        from backend.utils.memory_entry_validator import (
            validate_and_filter_entries,
        )

        # 1. build prompt
        prompt = build_extraction_prompt(turns)

        # 2. LLM call (errors → None；validator 会 reject)
        raw = await call_extraction_llm(prompt)
        if raw is None:
            return

        # 3. 拉现有 memory contents 做 duplicate 比对
        from backend.database.services import get_all_memories
        async with AsyncSessionLocal() as session:
            existing = await get_all_memories(
                session, user_id, active_only=True,
            )
        existing_contents = [m.content for m in existing if m.content]

        # 4. validator + filter
        min_conf = get_extractor_min_confidence()
        dup_th = get_extractor_dup_threshold()
        judge_on = get_extractor_llm_judge_enabled()
        llm_judge_fn = _make_llm_judge() if judge_on else None

        entries = await validate_and_filter_entries(
            raw,
            user_id=user_id,
            min_confidence=min_conf,
            dup_threshold=dup_th,
            existing_contents=existing_contents,
            llm_judge=llm_judge_fn,
        )
        if not entries:
            logger.info(
                "[extractor] user=%s turns=%d → 0 entries accepted",
                user_id, len(turns),
            )
            return

        # 5. save
        last_turn_id = turns[-1].id if turns else None
        await _save_worker_entries(
            user_id, entries, source_turn_id=last_turn_id,
        )
        logger.info(
            "[extractor] user=%s turns=%d → %d entries saved "
            "(source=worker, source_turn_id=%s)",
            user_id, len(turns), len(entries), last_turn_id,
        )

    async def run_loop(self) -> None:
        """主循环。任何 batch 异常吞 + log，sleep 后继续。"""
        interval = get_extractor_interval_seconds()
        logger.info(
            "[extractor] worker started interval=%ds batch_size=%d",
            interval, get_extractor_batch_size(),
        )
        while not self._stop_event.is_set():
            try:
                await self._extract_batch()
            except Exception:
                logger.exception("[extractor] batch raised; sleeping anyway")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=interval,
                )
            except asyncio.TimeoutError:
                pass  # 正常路径：到点继续 batch
        logger.info("[extractor] worker stopped")

    async def stop(self) -> None:
        """优雅 stop，让 ``run_loop`` 退出 while。"""
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("[extractor] stop timed out; cancelling")
                self._task.cancel()


# Module-level singleton — lifespan 拉起 / shutdown 调 stop。
_extractor_singleton: Optional[MemoryExtractor] = None


def get_extractor() -> MemoryExtractor:
    global _extractor_singleton
    if _extractor_singleton is None:
        _extractor_singleton = MemoryExtractor()
    return _extractor_singleton


def _reset_for_test() -> None:
    global _extractor_singleton
    _extractor_singleton = None


__all__ = [
    "ChatTurn",
    "MemoryExtractor",
    "fetch_user_turns_after",
    "get_extractor",
    "get_extractor_batch_size",
    "get_extractor_dup_threshold",
    "get_extractor_enabled",
    "get_extractor_interval_seconds",
    "get_extractor_llm_judge_enabled",
    "get_extractor_min_confidence",
    "get_last_processed_turn_id",
    "update_last_processed_turn_id",
]

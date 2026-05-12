"""v3.5 chunk 11 — structured profile_data 重生服务。

替代 chunk 9 ``ws._compute_profile_summary``（自然语言段落生成）的治本
方案。LLM 输出严格按 ``PROFILE_SCHEMA_V1`` JSON，validator hard-reject
违规输出，调用方保留旧 profile。

四种触发模式（mode 参数）：

  * ``cron``                  —— 每天凌晨 cron 触发，所有 user 自动重生
  * ``manual_incremental``    —— 用户 UI [增量更新] 按钮
  * ``manual_reset``          —— 用户 UI [完全重置] 按钮（不喂旧 profile）
  * ``delete_conversation``   —— DELETE conversation 触发（基于剩余 chat）

任何 mode 的"数据保护"：过去 ``input_days`` 天（默认 7）内 ``role='user'``
chat_history 行数 < ``min_user_messages``（默认 10）→ skip（不喂 LLM、
不动 DB）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select

from backend.config import config_yaml, get_planner_model
from backend.database import AsyncSessionLocal
from backend.database.models import ChatHistory, User
from backend.llm.client import LLMError, call_llm
from backend.utils.profile_schema import empty_profile
from backend.utils.profile_validator import validate_profile_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------


def _structured_cfg() -> dict:
    return ((config_yaml.get("memory") or {}).get("profile_structured") or {})


def get_profile_structured_enabled() -> bool:
    """chunk 11 总开关；False 时 cron job 不真跑。"""
    return bool(_structured_cfg().get("enabled", True))


def get_profile_input_days() -> int:
    """重生时取最近 N 天的 user 消息作输入。"""
    try:
        return int(_structured_cfg().get("input_days", 7))
    except (TypeError, ValueError):
        return 7


def get_profile_min_user_messages() -> int:
    """input_days 窗口内 user 消息 < N → skip。"""
    try:
        return int(_structured_cfg().get("min_user_messages", 10))
    except (TypeError, ValueError):
        return 10


def get_profile_cron_expr() -> str:
    """cron expression for profile_daily_regenerate。"""
    return str(_structured_cfg().get("cron", "55 23 * * *"))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_profile_data(user_id: str) -> Optional[dict]:
    """Read ``users.profile_data`` (JSON string) → dict.

    Returns None when row missing / column NULL / JSON parse failed (legacy
    rows shouldn't have that, but be defensive).
    """
    async with AsyncSessionLocal() as session:
        u = (await session.execute(
            select(User).where(User.user_id == user_id)
        )).scalar_one_or_none()
        if u is None or not u.profile_data:
            return None
        try:
            data = json.loads(u.profile_data)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            logger.warning(
                "[profile_regen] corrupt profile_data JSON user=%s, "
                "treating as None",
                user_id,
            )
    return None


async def save_profile_data(user_id: str, data: Optional[dict]) -> bool:
    """Write profile_data (or clear when ``data is None``).

    Returns True on success, False when user row missing (no-op).
    """
    async with AsyncSessionLocal() as session:
        u = (await session.execute(
            select(User).where(User.user_id == user_id)
        )).scalar_one_or_none()
        if u is None:
            return False
        if data is None:
            u.profile_data = None
        else:
            u.profile_data = json.dumps(data, ensure_ascii=False)
        await session.commit()
        return True


async def count_user_messages_within_days(user_id: str, days: int) -> int:
    """Count ``chat_history`` rows where role='user' AND kind='normal' AND
    created_at >= now - days。"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(func.count(ChatHistory.id))
            .where(ChatHistory.user_id == user_id)
            .where(ChatHistory.role == "user")
            .where(ChatHistory.kind == "normal")
            .where(ChatHistory.created_at >= cutoff)
        )).scalar()
        return int(row or 0)


async def fetch_recent_user_messages(user_id: str, days: int) -> list[str]:
    """Return ``role='user'`` ``kind='normal'`` message contents within window,
    oldest first (so LLM sees temporal order)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(ChatHistory.content)
            .where(ChatHistory.user_id == user_id)
            .where(ChatHistory.role == "user")
            .where(ChatHistory.kind == "normal")
            .where(ChatHistory.created_at >= cutoff)
            .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        )).all()
    return [r[0] or "" for r in rows if r[0]]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_profile_extraction_prompt(
    old_profile: Optional[dict],
    user_messages: list[str],
) -> str:
    """LLM 严格 JSON schema 重写 prompt。

    LLM contract：
      * 输出**必须**是合法 JSON，严格按 7 字段 schema（不多不少）
      * 只填能从用户消息直接看出的客观事实
      * 绝不写"感觉/情绪/印象/反推性描述"（"温柔陪伴" / "亲密关系" / "细腻
        敏感" / "需要被陪伴" 等）
      * 旧档案默认保留稳定特征
      * 近期数据明确不支持某字段 → 推翻 / 修改
      * 近期数据出现新的稳定特征 → 新增到对应 list
      * 不能确定的 string 字段填 ``null``，无内容的 list 字段填 ``[]``

    Returns:
        Prompt string ready for ``call_llm``。
    """
    old_json = (
        json.dumps(old_profile, ensure_ascii=False, indent=2)
        if old_profile is not None
        else "null"
    )
    # 每条 user 消息一行 ``- ...``；省 chat_history 顺序前缀（验证测试覆盖
    # _format_user_history 不带 [role:] 前缀的输入只读契约）
    msgs_block = "\n".join(f"- {m.strip()}" for m in user_messages if m and m.strip())
    if not msgs_block:
        msgs_block = "(空)"

    return f"""任务：基于以下输入更新用户客观档案 JSON。

旧档案（可能为 null）：
{old_json}

过去 7 天用户说过的话（role=user only）：
{msgs_block}

严格规则：
1. 输出**必须**是合法 JSON，严格按以下 7 字段 schema（不能多字段不能少字段）：
   - profession           : string | null
   - current_projects     : list[string]
   - communication_style  : string | null
   - interests            : list[string]
   - language_preferences : string | null
   - active_hours         : string | null
   - recurring_topics     : list[string]
2. **只填能从用户消息直接看出的客观事实**。
3. **绝不写"感觉 / 情绪 / 印象 / 反推性描述"**（如"细腻敏感"、"需要被陪
   伴"、"渴望温柔"、"亲密关系" 等）。任何主观、推测、温度感词都不要写。
4. 旧档案默认保留稳定特征。
5. 如近期数据明确不支持某字段，可推翻 / 修改。
6. 如近期数据出现旧档案没有的稳定特征，可新增到对应 list 字段。
7. 不能确定的 string 字段填 ``null``，无内容的 list 字段填 ``[]``。

只输出 JSON，不要加任何解释 / 前缀 / markdown 围栏。"""


# ---------------------------------------------------------------------------
# Core regen function
# ---------------------------------------------------------------------------


VALID_MODES = ("cron", "manual_incremental", "manual_reset", "delete_conversation")


async def _regenerate_profile_data(
    user_id: str,
    *,
    mode: str = "cron",
) -> tuple[str, Optional[dict]]:
    """Core regen. Returns ``(status, profile_or_none)``.

    Status values：

      * ``"regenerated"``         —— 成功，DB 已写新 profile，返新 dict
      * ``"skip_disabled"``       —— ``profile_structured.enabled = false``
      * ``"skip_too_few_user_msgs"`` —— 窗口内 user 行 < min_user_messages
      * ``"skip_llm_failed"``     —— LLM 调用异常
      * ``"skip_validator_rejected"`` —— validator 返 None（保留旧 profile）
      * ``"skip_user_not_found"`` —— 用户不存在

    mode 影响：

      * ``cron`` / ``manual_incremental`` / ``delete_conversation``
        → ``old_profile`` 喂 LLM 增量更新
      * ``manual_reset``
        → ``old_profile=None`` 喂 LLM（完全重置，丢弃旧档案）

    任何子步骤异常吞 + log，永远返回 status，不抛。
    """
    if mode not in VALID_MODES:
        logger.error(
            "[profile_regen] invalid mode user=%s mode=%s — defaulting to 'cron'",
            user_id, mode,
        )
        mode = "cron"

    if not get_profile_structured_enabled():
        logger.info(
            "[profile_regen] structured profile disabled by config user=%s",
            user_id,
        )
        return ("skip_disabled", None)

    # 1. 数据保护
    days = get_profile_input_days()
    min_msgs = get_profile_min_user_messages()
    cnt = await count_user_messages_within_days(user_id, days)
    if cnt < min_msgs:
        logger.info(
            "[profile_regen] skip user=%s mode=%s user_msgs_%dd=%d < min=%d",
            user_id, mode, days, cnt, min_msgs,
        )
        return ("skip_too_few_user_msgs", None)

    # 2. 旧 profile
    if mode == "manual_reset":
        old_profile: Optional[dict] = None
    else:
        old_profile = await get_profile_data(user_id)

    # 3. 最近 days 天 user 消息
    user_msgs = await fetch_recent_user_messages(user_id, days)

    # 4. LLM
    prompt = build_profile_extraction_prompt(old_profile, user_msgs)
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            model=get_planner_model(),
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
    except LLMError as exc:
        logger.error(
            "[profile_regen] LLM call failed user=%s mode=%s err=%s",
            user_id, mode, exc,
        )
        return ("skip_llm_failed", None)
    except Exception as exc:
        logger.exception(
            "[profile_regen] unexpected LLM error user=%s mode=%s err=%s",
            user_id, mode, exc,
        )
        return ("skip_llm_failed", None)

    # 5. validate
    new_profile = validate_profile_json(raw, user_id=user_id)
    if new_profile is None:
        logger.warning(
            "[profile_regen] validator rejected output user=%s mode=%s "
            "preview=%r — keeping old profile",
            user_id, mode, raw[:200],
        )
        return ("skip_validator_rejected", None)

    # 6. write back
    ok = await save_profile_data(user_id, new_profile)
    if not ok:
        logger.warning(
            "[profile_regen] user row missing on save user=%s",
            user_id,
        )
        return ("skip_user_not_found", None)
    logger.info(
        "[profile_regen] regenerated user=%s mode=%s user_msgs_count=%d",
        user_id, mode, cnt,
    )
    return ("regenerated", new_profile)


__all__ = [
    "build_profile_extraction_prompt",
    "count_user_messages_within_days",
    "empty_profile",
    "fetch_recent_user_messages",
    "get_profile_cron_expr",
    "get_profile_data",
    "get_profile_input_days",
    "get_profile_min_user_messages",
    "get_profile_structured_enabled",
    "save_profile_data",
    "_regenerate_profile_data",
    "VALID_MODES",
]

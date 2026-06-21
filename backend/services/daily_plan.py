"""DailyAgent Stage 1 — 每角色每日活动日程生成 + 持久化 + 查找。

照 ``backend/services/profile_regen.py`` 的 cron + LLM 单调用 pattern。
不做 mood 驱动 / 天气 / reflection / daily_summary 表 / 心跳 / react-replan /
渠道③ / 欲望向量(spec §6 显式排除)。

# Stage 1 MVP 范围

* 单角色:``DEFAULT_CHARACTER_ID = 1``(默认麻衣);Stage 2 扩 multi-character
  (代码处留 TODO)
* 一次 ``get_planner_model()`` LLM 调用,严格 JSON 数组输出
* 输出 schema: ``[{"start":"HH:MM","end":"HH:MM","activity":"短串"}, ...]``
* 输入 prompt A: 角色 persona / 昨天 plan / conversation_summary /
  用户 profile_data(标注是"陪伴对象") / 今日日历事件 / 今日日期 + 周几

# 链路

* cron ``5 0 * * *`` → ``daily_plan_generate()``
* startup(scheduler.start 后)→ ``daily_plan_backfill_if_missing()``
* ticker (5min interval) → ``backend/services/daily_ticker.py`` 查 today plan
  → 命中 slot 时写 ``character_states.current_activity``,空档清空

# 解析容错

LLM 输出包 ```json …``` 围栏 / 前后空白都剥;parse 或 validate 失败时
**保留昨天 plan 不覆盖**(不写 row)+ log warning。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text

from backend.config import config_yaml, get_planner_model
from backend.database import AsyncSessionLocal, engine
from backend.database.models import CharacterDailyPlan
from backend.llm.client import LLMError, call_llm
from backend.utils.chat_time import get_scheduler_tz_name, now_local, weekday_zh

logger = logging.getLogger(__name__)


# Stage 1 MVP — TODO Stage 2: iterate `characters` 表所有 row,user_id 按
# 最近交互的对话推断(LEFT JOIN conversations ORDER BY id DESC LIMIT 1)。
DEFAULT_CHARACTER_ID = 1


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _get_default_user_id() -> str:
    """配 ``default_user_id`` 缺省 ``"default"``,与 main.py:548 / 552 同源。"""
    return str(config_yaml.get("default_user_id", "default"))


# ---------------------------------------------------------------------------
# Parse / validate
# ---------------------------------------------------------------------------


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _is_hhmm(s: str) -> bool:
    return isinstance(s, str) and _HHMM_RE.match(s) is not None


def _strip_md_fence(raw: str) -> str:
    """LLM 偶发用 ```json ... ``` 围栏;剥外壳容忍。"""
    s = raw.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    return s


def _validate_plan_slots(plan_raw) -> Optional[list[dict]]:
    """要求 list[dict],每项 {start, end, activity} 三字段,start/end 是 HH:MM。

    返回 cleaned plan 或 None(任何 slot 违规 → 整 plan reject)。
    """
    if not isinstance(plan_raw, list) or not plan_raw:
        return None
    out: list[dict] = []
    for slot in plan_raw:
        if not isinstance(slot, dict):
            return None
        s = slot.get("start")
        e = slot.get("end")
        a = slot.get("activity")
        if not (isinstance(s, str) and isinstance(e, str) and isinstance(a, str)):
            return None
        if not _is_hhmm(s) or not _is_hhmm(e):
            return None
        cleaned_a = a.strip()
        if not cleaned_a:
            return None
        out.append({
            "start": s,
            "end": e,
            "activity": cleaned_a[:60],
        })
    return out


def _parse_plan_json(raw: str) -> Optional[list[dict]]:
    """LLM 输出 → 验证过的 plan list。空白 / markdown 围栏全容忍。"""
    if not raw:
        return None
    stripped = _strip_md_fence(raw)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return _validate_plan_slots(data)


# ---------------------------------------------------------------------------
# DB read / write
# ---------------------------------------------------------------------------


async def _load_plan(character_id: int, target_date: date) -> Optional[list[dict]]:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(CharacterDailyPlan).where(
                CharacterDailyPlan.character_id == character_id,
                CharacterDailyPlan.date == target_date,
            )
        )).scalar_one_or_none()
        if row is None:
            return None
        try:
            data = json.loads(row.plan)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "[daily_plan] corrupt plan JSON cid=%s date=%s",
                character_id, target_date,
            )
            return None
        if isinstance(data, list):
            return data
    return None


async def _save_today_plan(
    character_id: int, target_date: date, plan: list[dict],
) -> bool:
    """UPSERT 同 (character_id, date) 行;同行 plan 覆盖,新行 INSERT。"""
    plan_json = json.dumps(plan, ensure_ascii=False)
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(CharacterDailyPlan).where(
                CharacterDailyPlan.character_id == character_id,
                CharacterDailyPlan.date == target_date,
            )
        )).scalar_one_or_none()
        if existing is None:
            session.add(CharacterDailyPlan(
                character_id=character_id,
                date=target_date,
                plan=plan_json,
            ))
        else:
            existing.plan = plan_json
        await session.commit()
        return True


# ---------------------------------------------------------------------------
# Slot lookup (ticker 用)
# ---------------------------------------------------------------------------


def find_current_slot(
    plan: list[dict], now_hhmm: str,
) -> Optional[dict]:
    """plan list 内找命中当前 HH:MM 的 slot。

    支持跨午夜 slot(end < start),如 ``"23:30"-"07:00"`` 表"任何 HH:MM
    在 23:30..23:59 或 00:00..06:59 都命中"。
    """
    for slot in plan or []:
        s = slot.get("start") or ""
        e = slot.get("end") or ""
        if not s or not e:
            continue
        if s <= e:
            if s <= now_hhmm < e:
                return slot
        else:  # wraps midnight
            if now_hhmm >= s or now_hhmm < e:
                return slot
    return None


# ---------------------------------------------------------------------------
# Prompt A 输入 helpers
# ---------------------------------------------------------------------------


def _extract_character_name(persona, fallback_id: int) -> str:
    """从 ``LoadedPersona.identity`` 取角色名;缺失则回退 ``"角色{id}"``。

    Stage 1 实测对象是麻衣(cid=1),但 prompt 不写死名字 —— Stage 2 扩
    multi-character 时本函数 + UPSERT key 就够,prompt 模板零改动。

    常见 identity 字段:``name`` / ``full_name`` / ``display_name`` /
    ``nickname`` —— 按 priority 取首个非空。
    """
    ident = getattr(persona, "identity", None) or {}
    if isinstance(ident, dict):
        for key in ("name", "full_name", "display_name", "nickname"):
            v = ident.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return f"角色{fallback_id}"


def _extract_persona_blurb(persona) -> str:
    """从 ``LoadedPersona`` 拼简短 blurb 给 prompt(身份 + 性格 + 兴趣 +
    作息倾向)。任何字段缺失静默跳过。"""
    parts: list[str] = []
    ident = getattr(persona, "identity", None) or {}
    if isinstance(ident, dict) and ident:
        parts.append("身份:" + json.dumps(ident, ensure_ascii=False)[:300])
    pc = getattr(persona, "personality_core", None) or {}
    if isinstance(pc, dict) and pc:
        parts.append("性格:" + json.dumps(pc, ensure_ascii=False)[:300])
    rel = getattr(persona, "relationship_to_user", None) or {}
    if isinstance(rel, dict) and rel:
        parts.append("与用户关系:" + json.dumps(rel, ensure_ascii=False)[:200])
    lore = getattr(persona, "lore", None)
    if lore:
        parts.append("背景/兴趣/作息:" + json.dumps(lore, ensure_ascii=False)[:400])
    return "\n".join(parts) if parts else "(角色档案缺失)"


def _format_partner_profile(profile_data: Optional[dict]) -> str:
    """陪伴对象(用户)profile_data → 自然语言。复用
    ``profile_regen.format_profile_for_prompt``,空 → ``"(无)"``。
    """
    if not profile_data:
        return "(无)"
    try:
        from backend.services.profile_regen import format_profile_for_prompt
        formatted = format_profile_for_prompt(profile_data)
        return formatted or "(无)"
    except Exception:
        logger.exception("[daily_plan] format partner profile failed")
        return "(无)"


def _format_calendar(events: Optional[list[dict]]) -> str:
    """今日日历事件 → 每行一条简短描述;空 / None → ``"无特别安排"``。"""
    if not events:
        return "无特别安排"
    lines: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        title = str(ev.get("title") or "(无标题)").strip()
        start = ev.get("start") or ""
        end = ev.get("end") or ""
        location = ev.get("location") or ""
        # apple_calendar 返 ISO 字符串;只截 HH:MM
        s_hhmm = _iso_to_hhmm(start)
        e_hhmm = _iso_to_hhmm(end)
        time_part = f"{s_hhmm}-{e_hhmm}" if s_hhmm and e_hhmm else (s_hhmm or "")
        loc_part = f" @ {location}" if location else ""
        lines.append(f"- {time_part} {title}{loc_part}".strip())
    return "\n".join(lines) if lines else "无特别安排"


def _iso_to_hhmm(iso_str: str) -> str:
    """``"2026-06-21T08:30:00+09:00"`` → ``"08:30"``;失败返 ``""``。"""
    if not iso_str or not isinstance(iso_str, str):
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return ""


async def _load_today_calendar(
    today_local: date, tz_name: str,
) -> Optional[list[dict]]:
    """读今天 0:00..24:00 的日历事件。任何异常(权限 / AX 未授权 / 模块
    缺失)静默 → None。Prompt 端按 ``"无特别安排"`` 占位,不阻 plan 生成。
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        start = datetime(
            today_local.year, today_local.month, today_local.day, tzinfo=tz,
        )
        end = start + timedelta(days=1)
        from backend.integrations.apple_calendar import list_events_in_range
        events = await list_events_in_range(start, end, tz)
        return events or []
    except Exception as exc:
        logger.info(
            "[daily_plan] calendar fetch skipped (%s): %s",
            type(exc).__name__, exc,
        )
        return None


async def _load_recent_summary(
    user_id: str, character_id: int,
) -> Optional[str]:
    """从 ``conversation_summary`` 取最近非空 summary;失败 / 无 → None。"""
    try:
        async with engine.begin() as conn:
            row = (await conn.execute(text(
                "SELECT summary_text FROM conversation_summary "
                "WHERE user_id = :u AND character_id = :c "
                "  AND summary_text IS NOT NULL AND summary_text != '' "
                "ORDER BY updated_at DESC LIMIT 1"
            ), {"u": user_id, "c": character_id})).fetchone()
        if row is None:
            return None
        s = (row[0] or "").strip()
        return s or None
    except Exception:
        logger.exception(
            "[daily_plan] load summary failed user=%s char=%s",
            user_id, character_id,
        )
        return None


# ---------------------------------------------------------------------------
# Prompt A 全文
# ---------------------------------------------------------------------------


def build_daily_plan_prompt(
    *,
    character_name: str,
    today_date: str,
    weekday: str,
    persona_blurb: str,
    yesterday_plan: Optional[list[dict]],
    conversation_summary: Optional[str],
    profile_data: Optional[dict],
    today_calendar: Optional[list[dict]],
) -> str:
    """Prompt A 全文。``character_name`` 从 ``character_personas.identity``
    取,Stage 2 扩 multi-character 时零模板改动。
    """
    yesterday_block = (
        json.dumps(yesterday_plan, ensure_ascii=False)
        if yesterday_plan
        else "(无记录,按她/他的性格自然安排)"
    )
    summary_block = conversation_summary or "(暂无可用摘要)"
    profile_block = _format_partner_profile(profile_data)
    calendar_block = _format_calendar(today_calendar)

    return f"""你在为「{character_name}」规划 {today_date}({weekday})的一天作息。

【{character_name}是谁】
{persona_blurb}
←(这是她/他活动的根)

【昨天做了什么】
{yesterday_block}

【你俩最近聊了啥】
{summary_block}

【用户(陪伴对象)情况 · 仅参考 · 不是{character_name}自己】
{profile_block}

【今天】{weekday};日历:
{calendar_block}

要求:
1. ★活动必须从{character_name}的性格和兴趣长出来 —— 爱画画就有画画的块、内向就独处多。禁止"工作/休息/吃饭"这类通用占位。
2. 每个活动要具体:写"画窗外雨景的水彩",不写"画画";写"重读《XX》第三章",不写"看书"。
3. 块连续、覆盖一整天(含睡眠,如 23:30-07:00 睡觉),时段不重叠、按时间先后、不留空档。
4. 贴合今天是 {weekday}(工作日/周末作息不同)。
5. 跟昨天有延续(没看完的书接着读、提过的计划落地),但别跟昨天一模一样,要有自然变化。
6. 5-8 个块(含睡眠块)。

只输出 JSON 数组(时间 24h HH:MM,无多余文字、无 markdown):
[{{"start":"08:30","end":"10:00","activity":"具体在做什么"}}, ...]"""


# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------


async def _generate_for_character(
    character_id: int,
    *,
    user_id: str,
    today_local: date,
) -> tuple[str, Optional[list[dict]]]:
    """Returns ``(status, plan_or_none)``。

    Status 值:

      * ``"generated"``           — LLM 成功,plan 已 UPSERT
      * ``"skip_persona_missing"`` — load_active_persona 抛错(character 无 active variant)
      * ``"skip_llm_failed"``      — LLM 调用异常
      * ``"skip_parse_failed"``    — JSON parse / validate 失败(保留昨天 plan)
    """
    # 1. persona
    try:
        from backend.agents.prompt.persona_loader import load_active_persona
        persona = await load_active_persona(character_id)
    except Exception:
        logger.exception(
            "[daily_plan] persona load failed cid=%s", character_id,
        )
        return ("skip_persona_missing", None)

    persona_blurb = _extract_persona_blurb(persona)
    character_name = _extract_character_name(persona, character_id)

    # 2. yesterday plan(跨天延续)
    yesterday = today_local - timedelta(days=1)
    yesterday_plan = await _load_plan(character_id, yesterday)

    # 3. recent conversation summary
    summary = await _load_recent_summary(user_id, character_id)

    # 4. partner profile_data(标注是"陪伴对象")
    try:
        from backend.services.profile_regen import get_profile_data
        profile = await get_profile_data(user_id)
    except Exception:
        logger.exception("[daily_plan] partner profile load failed user=%s", user_id)
        profile = None

    # 5. 今日日历
    tz_name = get_scheduler_tz_name()
    calendar_events = await _load_today_calendar(today_local, tz_name)

    # 6. 日期 / 周几
    today_dt = datetime(today_local.year, today_local.month, today_local.day)
    weekday = weekday_zh(today_dt)
    today_date_str = today_local.strftime("%Y-%m-%d")

    # 7. build prompt
    prompt = build_daily_plan_prompt(
        character_name=character_name,
        today_date=today_date_str,
        weekday=weekday,
        persona_blurb=persona_blurb,
        yesterday_plan=yesterday_plan,
        conversation_summary=summary,
        profile_data=profile,
        today_calendar=calendar_events,
    )

    # 8. LLM
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            model=get_planner_model(),
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
    except LLMError as exc:
        logger.error(
            "[daily_plan] LLM call failed cid=%s err=%s", character_id, exc,
        )
        return ("skip_llm_failed", None)
    except Exception as exc:
        logger.exception(
            "[daily_plan] LLM unexpected error cid=%s err=%s", character_id, exc,
        )
        return ("skip_llm_failed", None)

    # 9. parse + validate
    parsed = _parse_plan_json(raw)
    if parsed is None:
        logger.warning(
            "[daily_plan] parse/validate failed cid=%s preview=%r — "
            "keeping previous plan untouched",
            character_id, raw[:200],
        )
        return ("skip_parse_failed", None)

    # 10. save
    try:
        await _save_today_plan(character_id, today_local, parsed)
    except Exception:
        logger.exception(
            "[daily_plan] save failed cid=%s date=%s", character_id, today_local,
        )
        return ("skip_parse_failed", None)
    logger.info(
        "[daily_plan] generated cid=%s date=%s slots=%d",
        character_id, today_local, len(parsed),
    )
    return ("generated", parsed)


# ---------------------------------------------------------------------------
# Cron + startup entries
# ---------------------------------------------------------------------------


async def daily_plan_generate() -> None:
    """Cron entry — ``5 0 * * *`` 每天 0:05(错开 0:00 的 intimacy_decay)。

    Stage 1 MVP: 只跑 ``DEFAULT_CHARACTER_ID``。Stage 2 扩 multi-character。
    """
    tz_name = get_scheduler_tz_name()
    today_local = now_local(tz_name).date()
    user_id = _get_default_user_id()
    logger.info(
        "[cron] daily_plan_generate firing cid=%s date=%s user=%s",
        DEFAULT_CHARACTER_ID, today_local, user_id,
    )
    try:
        status, _ = await _generate_for_character(
            DEFAULT_CHARACTER_ID, user_id=user_id, today_local=today_local,
        )
        logger.info(
            "[cron] daily_plan_generate done cid=%s date=%s status=%s",
            DEFAULT_CHARACTER_ID, today_local, status,
        )
    except Exception:
        logger.exception(
            "[cron] daily_plan_generate failed cid=%s", DEFAULT_CHARACTER_ID,
        )


async def daily_plan_backfill_if_missing() -> None:
    """Startup entry — 若今天还没 plan,补生成一次。

    覆盖三种场景:
      * 应用首次启动当天(cron 还没跑过)
      * 进程 0:05 之前被启动(cron 那时刻还没触发)
      * 任何原因导致今日 row 缺失(磁盘 / 之前 LLM 全失败 / 手动删行)
    """
    tz_name = get_scheduler_tz_name()
    today_local = now_local(tz_name).date()
    try:
        existing = await _load_plan(DEFAULT_CHARACTER_ID, today_local)
    except Exception:
        logger.exception(
            "[daily_plan] backfill load_plan failed cid=%s — skip backfill",
            DEFAULT_CHARACTER_ID,
        )
        return
    if existing is not None:
        logger.info(
            "[daily_plan] backfill skip — plan already exists cid=%s date=%s slots=%d",
            DEFAULT_CHARACTER_ID, today_local, len(existing),
        )
        return
    user_id = _get_default_user_id()
    logger.info(
        "[daily_plan] backfill firing cid=%s date=%s user=%s",
        DEFAULT_CHARACTER_ID, today_local, user_id,
    )
    try:
        status, _ = await _generate_for_character(
            DEFAULT_CHARACTER_ID, user_id=user_id, today_local=today_local,
        )
        logger.info(
            "[daily_plan] backfill done cid=%s status=%s",
            DEFAULT_CHARACTER_ID, status,
        )
    except Exception:
        logger.exception(
            "[daily_plan] backfill failed cid=%s", DEFAULT_CHARACTER_ID,
        )


__all__ = [
    "DEFAULT_CHARACTER_ID",
    "build_daily_plan_prompt",
    "daily_plan_backfill_if_missing",
    "daily_plan_generate",
    "find_current_slot",
]

"""v3.5 chunk 8a-ext — ActivityJudge: 慢路径"是否值得主动说话"LLM 判断。

设计原则
========

* **跟快路径并存**: chunk 8a 硬编码 trigger(IDE/音乐/技术文档/long_focus/
  late_night)覆盖明确场景。Judge 只在快路径**没命中**且用户停留 ≥
  min_stay_minutes 时跑。用户切到 IDE 触发快路径就不再 judge,省 LLM 钱
* **便宜模型**: ``get_planner_model()`` 返 qwen-turbo,对齐 chunk 10
  extractor / chunk 11 profile regenerator 同模型
* **silent failure**: judge LLM 异常 / 网络 / parse 失败 → 返 None,
  ActivityWatcher poll_listener 继续 polling 不阻塞
* **节流**: 同 stay_key (e.g. ``"url:<url>"``) 10 min 内不重复 judge
* **共享 daily_cap**: 不维护独立计数器,fire 由 ``activity_smart``
  ``_today_count`` 统一管。本模块只做决策

LLM 输出契约
============

JSON object(markdown fence 容错复用 chunk 10/11 pattern):

```json
{
  "speak": true | false,
  "reason": "<10 字内>",
  "topic_hint": "<若 speak=true,Momo 该提什么话题,20 字内,可空>"
}
```

判断准则(prompt 内):
* 私密 (银行/邮箱/密码管理器) → false(实际已被 ActivityWatcher 黑名单
  挡掉,judge 看不到 URL,但 prompt 提一下保险)
* IDE/编辑器长时间专注 → 已被快路径 ide_open + long_focus 覆盖,judge
  看不到(快路径已 fire)
* 娱乐/社交/视频长停留 → 沉浸中不打扰,倾向 false
* 找资料/学习/公开网页 → 适合 chime in,倾向 true
* 求职/查日程/看新闻 → 适合关心一句,倾向 true
* 今日已用 >= cap*0.8 → 严格 false(快用完配额)
* since_last_speak < 5 min → false(刚说过)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from backend.config import config_yaml, get_planner_model
from backend.llm.client import LLMError, call_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------


def _cfg() -> dict:
    return config_yaml.get("activity_judge") or {}


def get_judge_enabled() -> bool:
    """活动 judge 总开关。默认 ON (用户明确要陪伴感),SettingsPanel toggle 可关。"""
    return bool(_cfg().get("enabled", True))


def get_judge_model() -> str:
    """便宜模型(qwen-turbo),与 chunk 10/11 同源。"""
    val = _cfg().get("model")
    if isinstance(val, str) and val.strip():
        return val
    return get_planner_model()


def get_min_stay_minutes() -> int:
    try:
        return max(1, int(_cfg().get("min_stay_minutes", 5)))
    except (TypeError, ValueError):
        return 5


def get_judge_throttle_minutes() -> int:
    try:
        return max(1, int(_cfg().get("throttle_minutes", 10)))
    except (TypeError, ValueError):
        return 10


def get_prompt_max_chars() -> int:
    try:
        return max(200, int(_cfg().get("prompt_max_chars", 2000)))
    except (TypeError, ValueError):
        return 2000


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeDecision:
    speak: bool
    reason: str
    topic_hint: Optional[str]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_JUDGE_PROMPT_TEMPLATE = """你是 AI 陪伴 Momo,正在决定是否主动找用户说话。

当前用户状态:
- App: {app}
- URL: {url}
- 页面标题: {title}
- 页面内容摘要: {content_snippet}
- 已停留: {minutes} 分钟
- 距用户上次跟 Momo 说话: {since_last_speak_str}
- 今日 Momo 已主动说话: {today_count}/{daily_cap} 次

判断: **此时**主动说话会让用户开心还是烦?

判断准则:
- 私密内容(银行/邮箱/密码管理器) → speak=false
- 用户在 IDE / 编辑器专注思考 → 已被快路径覆盖,慢路径直接 false
- 用户浏览娱乐 / 社交 / 视频(超过 10 分钟)→ 沉浸中不打扰,倾向 false
- 用户在找资料 / 学习 / 浏览公开网页(教程 / 文档 / 博客)→ 适合 chime in
- 用户在求职 / 查日程 / 看新闻 / 知识类(科普/百科)→ 适合关心一句
- 今日已说话 >= daily_cap * 0.8 → 严格 false(配额快用完)
- 距上次说话 < 5 分钟 → speak=false(刚聊过不再打扰)
- 不确定 → 倾向 speak=false(沉默永远比骚扰好)

**只返 JSON,不要其他内容**:
{{"speak": true|false, "reason": "<10 字内>", "topic_hint": "<10-20 字 Momo 该提什么话题,speak=false 可空>"}}
"""


def _build_judge_prompt(
    *,
    app: Optional[str],
    url: Optional[str],
    title: str,
    content_snippet: str,
    minutes: float,
    since_last_speak_minutes: Optional[float],
    today_count: int,
    daily_cap: int,
    max_chars: int,
) -> str:
    """组装 judge prompt。``content_snippet`` 超 max_chars 时截断 + 加 …。"""
    snip = (content_snippet or "").strip()
    if len(snip) > max_chars:
        snip = snip[:max_chars].rstrip() + "…"
    if not snip:
        snip = "(无 / 未抓取)"
    if since_last_speak_minutes is None:
        since_str = "未知 / 从未聊过"
    elif since_last_speak_minutes >= 60:
        since_str = f"{since_last_speak_minutes/60:.1f} 小时"
    else:
        since_str = f"{since_last_speak_minutes:.0f} 分钟"
    return _JUDGE_PROMPT_TEMPLATE.format(
        app=app or "(未知)",
        url=url or "(无 / 非浏览器)",
        title=title or "(无)",
        content_snippet=snip,
        minutes=int(minutes),
        since_last_speak_str=since_str,
        today_count=today_count,
        daily_cap=daily_cap,
    )


# ---------------------------------------------------------------------------
# LLM call + JSON parse(markdown fence 容错)
# ---------------------------------------------------------------------------


_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")


async def _call_judge_llm(prompt: str) -> Optional[str]:
    """调 qwen-turbo 拿 raw response。失败 → None + log,不抛。"""
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            model=get_judge_model(),
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
        return raw
    except LLMError as exc:
        logger.warning("[activity_judge] LLM call failed: %s", exc)
        return None
    except Exception as exc:  # pragma: no cover - 防御
        logger.warning("[activity_judge] unexpected LLM error: %s", exc)
        return None


def _parse_judge_output(raw: Optional[str]) -> Optional[JudgeDecision]:
    """LLM raw → JudgeDecision 或 None。容忍 markdown fence + 多种 JSON quirk。

    复用 chunk 10/11 fence pattern:
      ```json {...} ```  或  ``` {...} ```
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_OPEN_RE.sub("", cleaned)
        cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[activity_judge] JSON parse failed: %s preview=%r", exc, cleaned[:200],
        )
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "[activity_judge] top-level not dict, got %s", type(parsed).__name__,
        )
        return None
    speak = parsed.get("speak")
    if not isinstance(speak, bool):
        # 容忍 "true"/"false" 字符串 / 1/0 数字
        if isinstance(speak, str):
            speak = speak.strip().lower() in ("true", "yes", "1")
        elif isinstance(speak, (int, float)):
            speak = bool(speak)
        else:
            logger.warning("[activity_judge] speak field invalid: %r", speak)
            return None
    reason = str(parsed.get("reason", "") or "").strip()[:40]
    topic_hint_raw = parsed.get("topic_hint", "") or ""
    topic_hint = str(topic_hint_raw).strip()[:80] if topic_hint_raw else None
    return JudgeDecision(speak=bool(speak), reason=reason, topic_hint=topic_hint or None)


# ---------------------------------------------------------------------------
# State + throttle
# ---------------------------------------------------------------------------


_last_judged_per_key: dict[str, float] = {}


def _is_throttled(stay_key: str, throttle_seconds: int) -> bool:
    last = _last_judged_per_key.get(stay_key, 0.0)
    return (time.time() - last) < throttle_seconds


def _record_judged(stay_key: str) -> None:
    _last_judged_per_key[stay_key] = time.time()


def reset_state_for_test() -> None:
    """**测试专用**: 清节流字典。"""
    _last_judged_per_key.clear()


# ---------------------------------------------------------------------------
# Public top-level: maybe_judge
# ---------------------------------------------------------------------------


async def maybe_judge(
    *,
    stay_info: dict,
    content_snippet: str = "",
    today_count: int = 0,
    daily_cap: int = 5,
    since_last_speak_minutes: Optional[float] = None,
) -> Optional[JudgeDecision]:
    """主入口: 看条件 + 调 LLM + 解析决策。

    返:
      * ``None`` —— 没跑 judge(条件不满足 / throttle / LLM 失败 / parse 失败)
      * ``JudgeDecision(speak=bool, reason=str, topic_hint=str|None)``

    Caller(activity_smart)负责后续 daily_cap 检查 + fire trigger。本函数
    **不**写 daily_count(由 caller 在 fire 之后做),便于职责分离。
    """
    if not get_judge_enabled():
        return None
    if not stay_info:
        return None
    stay_key = stay_info.get("key") or ""
    duration_sec = float(stay_info.get("duration_seconds") or 0.0)
    min_stay_sec = get_min_stay_minutes() * 60
    if duration_sec < min_stay_sec:
        # 没到 min_stay,不打 LLM(频繁短停 → 不 judge,正常 watcher polling 继续)
        return None
    if _is_throttled(stay_key, get_judge_throttle_minutes() * 60):
        logger.info(
            "[activity_judge] throttled: key=%s last_judged < %d min",
            stay_key, get_judge_throttle_minutes(),
        )
        return None

    # 进入 LLM 调用 — 先记账(防 LLM 慢 / 失败时下一拍立刻重试)
    _record_judged(stay_key)

    prompt = _build_judge_prompt(
        app=stay_info.get("app"),
        url=stay_info.get("url"),
        title=stay_info.get("title", ""),
        content_snippet=content_snippet,
        minutes=duration_sec / 60.0,
        since_last_speak_minutes=since_last_speak_minutes,
        today_count=today_count,
        daily_cap=daily_cap,
        max_chars=get_prompt_max_chars(),
    )
    logger.info(
        "[activity_judge] judging: key=%s duration=%.1fmin today=%d/%d",
        stay_key, duration_sec / 60.0, today_count, daily_cap,
    )
    raw = await _call_judge_llm(prompt)
    decision = _parse_judge_output(raw)
    if decision is None:
        logger.info("[activity_judge] judge LLM returned no decision (parse fail or empty)")
        return None
    logger.info(
        "[activity_judge] decision: speak=%s reason=%r topic_hint=%r key=%s",
        decision.speak, decision.reason, decision.topic_hint, stay_key,
    )
    return decision

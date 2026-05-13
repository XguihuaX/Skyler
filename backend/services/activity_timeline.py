"""V3.5 chunk 14 — activity_timeline session writer。

跟 chunk 8a-ext judge **平行**的第二个 poll-listener,但**不**用于触发对话:
观察 ``ActivityState`` 流,在 ``(active_app, browser_url)`` 元组发生变化的
那一拍把**上一段** stay 写成一条 ``activity_sessions`` 行。chunk 8a-ext
judge 用来当下 chime in;本模块用来"明天回看 / Momo 引用今日活动"。

设计要点
========

* **Poll-listener,不是 change-listener**
  chunk 8a-ext judge 同样走 ``register_poll_listener``。直接 hook
  ``_detect_changes`` 看似自然,但:
    - ``_detect_changes`` 在触发 listener 前就 reset 了 ``_url_dwell_start``
      / ``_app_focus_start`` → duration 信息丢失
    - long_dwell / long_focus latching 把 timer 设成 ``-1.0`` → duration
      算出来是负的
  本模块自己维护一份"上一段 stay"游标(``_prev_app`` / ``_prev_url`` /
  ``_prev_start_at``),与 watcher 内部 timer 解耦,逻辑直观。
* **元组 (app, url) 变化 = stay 边界**
  app 切了一定算 boundary;同 app 内 URL 切了也算 boundary(用户在 Chrome
  从 github 切 bilibili,即便没换 app,session 也是两段)。
* **30s 起跳过滤**
  duration < ``min_session_seconds``(默 30)直接不写。短切换无意义,
  也减小 DB 行数。同时这个阈值与 watcher ``poll_interval_seconds=30``
  天然对齐 —— sub-poll 切换看不到。
* **黑名单复用 chunk 8a**
  ``activity_watcher.get_blocked_apps()`` / ``get_blocked_url_patterns()``
  + ``url_fetcher.is_url_blocked`` —— session 写入前重新过一道(虽然 snapshot
  已经过滤过,但 watcher black-listed app 仍然进了 active_app 字段为 None,
  会被分到 ``"(unknown)"``,这里再过滤一次 defensive)。
* **chunk 8a-ext V2 idle 标记**
  写时若 macOS idle > V2 阈值 → ``is_idle_filtered=1``。session 仍然
  写入(timeline UI 显示完整记录),但 capability summary 计算时 caller
  可选 exclude。
* **总开关 ``activity_timeline.enabled``(默 ON)**
  关掉后 watcher 仍跑(chime in 不破),只是不写表。

公共 API
========

* ``session_writer_poll_handler(state: ActivityState) -> None``
* ``get_timeline_enabled() -> bool``
* ``get_min_session_seconds() -> int``
* ``categorize(app, url) -> str``  (other / ide / browser / music / ...)
* ``reset_state_for_test() -> None``
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from backend.config import config_yaml
from backend.database import engine
from backend.integrations import activity_watcher as _aw
from backend.integrations import url_fetcher as _uf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _cfg() -> dict:
    return config_yaml.get("activity_timeline") or {}


def get_timeline_enabled() -> bool:
    """``activity_timeline.enabled``(默 True)。"""
    val = _cfg().get("enabled", True)
    return bool(val)


def get_min_session_seconds() -> int:
    """短 session 过滤阈值(默 30s,与 watcher poll_interval 同步)。"""
    try:
        return max(0, int(_cfg().get("min_session_seconds", 30)))
    except (TypeError, ValueError):
        return 30


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------


# 与 activity_smart._IDE_APPS / _MUSIC_APPS / _TECH_DOC_URL_PATTERNS 共用同一
# 套规则集是有意的 — 同一个 app 在 chime-in 决策路径和 timeline 归类路径
# 该归同一 category,不该出现 "judge 觉得是 IDE 但 timeline 标 browser"
# 这种语义裂缝。
from backend.proactive.activity_smart import (  # noqa: E402  late import 避循环
    _IDE_APPS, _MUSIC_APPS, _TECH_DOC_URL_PATTERNS,
)


# 视频网站常见 host 子串(timeline 归类用,不参与 chime-in 决策)
_VIDEO_URL_PATTERNS = (
    "youtube.com", "bilibili.com/video", "youku.com", "iqiyi.com",
    "v.qq.com", "netflix.com", "twitch.tv",
)

# 社交媒体 host 子串
_SOCIAL_URL_PATTERNS = (
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "weibo.com", "reddit.com", "linkedin.com", "xiaohongshu.com",
)

# 浏览器 app(与 activity_monitor._BROWSER_APPS 同源,但这里小写匹配 —
# activity_monitor 那份是 lower set,直接复用一致)
from backend.integrations.activity_monitor import _BROWSER_APPS  # noqa: E402


def categorize(app: Optional[str], url: Optional[str]) -> str:
    """返 'ide' / 'browser' / 'music' / 'video' / 'social' / 'other'。

    优先级:URL 命中 > app 命中。理由:用户开 Chrome 看 youtube,
    应分到 video 而不是 browser。
    """
    if url:
        u = url.lower()
        if any(p in u for p in _VIDEO_URL_PATTERNS):
            return "video"
        if any(p in u for p in _SOCIAL_URL_PATTERNS):
            return "social"
        if any(p in u for p in _TECH_DOC_URL_PATTERNS):
            return "tech_doc"
    if app:
        a = app.strip().lower()
        if a in _IDE_APPS:
            return "ide"
        if a in _MUSIC_APPS:
            return "music"
        if a in _BROWSER_APPS:
            return "browser"
    return "other"


# ---------------------------------------------------------------------------
# Blacklist (复用 chunk 8a)
# ---------------------------------------------------------------------------


def _is_blacklisted(app: Optional[str], url: Optional[str]) -> bool:
    if app:
        blocked = set(_aw.get_blocked_apps() or [])
        if app in blocked:
            return True
    if url:
        patterns = _aw.get_blocked_url_patterns() or []
        if _uf.is_url_blocked(url, patterns):
            return True
    return False


# ---------------------------------------------------------------------------
# Idle awareness (chunk 8a-ext V2)
# ---------------------------------------------------------------------------


def _is_user_idle() -> bool:
    """**borrow** chunk 8a-ext V2 idle 检测;返 True 表示该 session 应标 idle_filtered。

    threshold 直接复用 ``activity_judge.get_idle_threshold_seconds()``(默 300s)
    —— 没有理由让 timeline 用不同的阈值。``get_idle_seconds()`` 返 None
    (非 macOS / ioreg fail)→ 视作活跃(not idle),与 chunk 8a-ext V2
    fallback 行为一致。
    """
    try:
        from backend.integrations.activity_monitor import get_idle_seconds
        from backend.proactive.activity_judge import get_idle_threshold_seconds
        idle_sec = get_idle_seconds()
        threshold = get_idle_threshold_seconds()
        if idle_sec is None or threshold <= 0:
            return False
        return idle_sec > threshold
    except Exception as exc:
        logger.debug("[activity_timeline] idle probe failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Session boundary tracker(模块级 — single watcher 单 user 即够)
# ---------------------------------------------------------------------------


_prev_app: Optional[str] = None
_prev_url: Optional[str] = None
_prev_title: Optional[str] = None
_prev_start_at: Optional[datetime] = None
_prev_idle: bool = False


def reset_state_for_test() -> None:
    """单元测试钩子,清模块状态。"""
    global _prev_app, _prev_url, _prev_title, _prev_start_at, _prev_idle
    _prev_app = None
    _prev_url = None
    _prev_title = None
    _prev_start_at = None
    _prev_idle = False


def _get_default_user_id() -> str:
    return str(config_yaml.get("default_user_id") or "default")


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------


async def _write_session(
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
    duration_seconds: int,
    app_name: str,
    browser_url: Optional[str],
    browser_title: Optional[str],
    category: str,
    is_idle_filtered: bool,
) -> Optional[int]:
    """INSERT 一行 activity_sessions。返新行 id 或 None(失败)。"""
    try:
        async with engine.begin() as conn:
            res = await conn.execute(text("""
                INSERT INTO activity_sessions (
                    user_id, start_at, end_at, duration_seconds,
                    app_name, browser_url, browser_title,
                    category, is_idle_filtered
                ) VALUES (
                    :user_id, :start_at, :end_at, :duration_seconds,
                    :app_name, :browser_url, :browser_title,
                    :category, :is_idle_filtered
                )
            """), {
                "user_id": user_id,
                "start_at": start_at,
                "end_at": end_at,
                "duration_seconds": duration_seconds,
                "app_name": app_name,
                "browser_url": browser_url,
                "browser_title": browser_title,
                "category": category,
                "is_idle_filtered": 1 if is_idle_filtered else 0,
            })
        return getattr(res, "lastrowid", None)
    except Exception as exc:
        logger.exception("[activity_timeline] DB write failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public: poll-listener handler
# ---------------------------------------------------------------------------


async def session_writer_poll_handler(state) -> None:
    """挂到 ``activity_watcher.register_poll_listener`` 上,每 poll 跑一次。

    元组 ``(app, url)`` 与上一拍比对:
      * 相同 → no-op(stay 还在进行)
      * 不同 → 上一段 stay 结束,写一条 session;打点新一段开始

    总开关 ``activity_timeline.enabled=false`` → 跟踪游标继续更新但不写 DB
    (用户随时打开后 timeline 立即开始 from-now 记录,不会留下空洞)。
    """
    global _prev_app, _prev_url, _prev_title, _prev_start_at, _prev_idle

    now = datetime.utcnow()
    new_app = getattr(state, "active_app", None)
    browser = getattr(state, "browser", None) or {}
    new_url = browser.get("url") if isinstance(browser, dict) else None
    new_title = browser.get("title") if isinstance(browser, dict) else None

    # 元组无变化:仍在同一段 stay,只更新 idle 标记(如果新拍 idle 中,
    # 上段也算 idle 段)。
    if new_app == _prev_app and new_url == _prev_url:
        if not _prev_idle and _is_user_idle():
            _prev_idle = True
        return

    # 边界:上一段 stay 结束,尝试写入
    if (
        _prev_app is not None
        and _prev_start_at is not None
    ):
        duration = int((now - _prev_start_at).total_seconds())
        min_sec = get_min_session_seconds()
        enabled = get_timeline_enabled()

        if duration < min_sec:
            logger.debug(
                "[activity_timeline] skip short session: app=%r url=%r duration=%ds < %ds",
                _prev_app, _prev_url, duration, min_sec,
            )
        elif _is_blacklisted(_prev_app, _prev_url):
            logger.info(
                "[activity_timeline] session blacklisted, skipped: app=%r url_present=%s",
                _prev_app, _prev_url is not None,
            )
        elif not enabled:
            logger.debug(
                "[activity_timeline] disabled, skip write: app=%r duration=%ds",
                _prev_app, duration,
            )
        else:
            cat = categorize(_prev_app, _prev_url)
            new_id = await _write_session(
                user_id=_get_default_user_id(),
                start_at=_prev_start_at,
                end_at=now,
                duration_seconds=duration,
                app_name=_prev_app,
                browser_url=_prev_url,
                browser_title=_prev_title,
                category=cat,
                is_idle_filtered=_prev_idle,
            )
            if new_id is not None:
                logger.info(
                    "[activity_timeline] session written: id=%d app=%r "
                    "category=%s duration=%ds idle=%s url_present=%s",
                    new_id, _prev_app, cat, duration,
                    _prev_idle, _prev_url is not None,
                )

    # 打点新一段
    _prev_app = new_app
    _prev_url = new_url
    _prev_title = new_title
    _prev_start_at = now if new_app is not None else None
    _prev_idle = _is_user_idle() if new_app is not None else False


# ---------------------------------------------------------------------------
# v3.5 chunk 14 commit 5 — ChatAgent system prompt 注入(模板,不调 LLM)
# ---------------------------------------------------------------------------


def get_inject_enabled() -> bool:
    """``activity_timeline.inject_into_chat`` (默 True)。

    与 ``enabled`` 分开:enabled=True / inject=False 表示"记录但不让 Momo
    在对话里主动提" — 给追求隐私 / 注入噪音少的用户。
    """
    val = _cfg().get("inject_into_chat", True)
    return bool(val)


def _fmt_duration_zh(seconds: int) -> str:
    """秒数 → "X 小时 Y 分钟" / "X 分钟" 中文短串(注入 prompt 用)。"""
    if seconds < 60:
        return f"{seconds}秒"
    if seconds < 3600:
        return f"{seconds // 60}分钟"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if m == 0:
        return f"{h}小时"
    return f"{h}小时{m}分钟"


async def format_today_activity_for_prompt(
    user_id: str,
) -> Optional[str]:
    """生成今日活动摘要文本块给 ChatAgent system prompt 注入。

    返:
      * 完整文本块(``## 用户今日活动\\n...``) — 数据有意义
      * ``None`` —— 关掉注入 / 今日数据 < 60s / DB 异常

    模板化(零 LLM 调用)与 ``format_profile_for_prompt`` 同思路。

    输出例:
    ```
    ## 用户今日活动
    今天已活跃 7小时30分钟。

    主要花在:
    - Visual Studio Code 3小时
    - Google Chrome 2小时(主要看 jobs.bilibili.com 招聘 1小时35分钟)
    - 网易云音乐 1小时

    最近 30 分钟主要在: Visual Studio Code
    ```
    """
    if not get_inject_enabled():
        return None

    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    recent_cutoff = now - timedelta(minutes=30)

    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT app_name, browser_url, browser_title, "
                "       duration_seconds, start_at "
                "FROM activity_sessions "
                "WHERE user_id = :uid "
                "  AND start_at >= :s AND start_at < :e "
                "  AND is_idle_filtered = 0 "
                "ORDER BY start_at ASC"
            ), {"uid": user_id, "s": start, "e": end})).fetchall()
    except Exception as exc:
        logger.debug(
            "[activity_timeline] inject query failed (skipping): %s", exc,
        )
        return None

    if not rows:
        return None

    total = 0
    app_agg: dict[str, dict] = {}
    recent_app: Optional[str] = None
    for app, url, title, dur, sat in rows:
        d = int(dur)
        total += d
        a = app_agg.setdefault(app, {
            "total": 0, "top_url": None, "top_url_title": None, "top_url_seconds": 0,
        })
        a["total"] += d
        if url and d > a["top_url_seconds"]:
            a["top_url"] = url
            a["top_url_title"] = title or ""
            a["top_url_seconds"] = d
        try:
            sat_dt = sat if isinstance(sat, datetime) else datetime.fromisoformat(str(sat))
        except (ValueError, TypeError):
            sat_dt = None
        if sat_dt is not None and sat_dt >= recent_cutoff:
            recent_app = app

    # 噪音过滤:总活跃 < 60s 不注入(刚启动 / 短时使用,信息无价值)
    if total < 60:
        return None

    lines = ["## 用户今日活动"]
    lines.append(f"今天已活跃 {_fmt_duration_zh(total)}。")
    lines.append("")
    lines.append("主要花在:")
    # top 5 apps 注入,避免 prompt 过长
    top5 = sorted(
        app_agg.items(), key=lambda kv: -kv[1]["total"],
    )[:5]
    for app, info in top5:
        line = f"- {app} {_fmt_duration_zh(info['total'])}"
        if info["top_url"]:
            # URL 简化:取 host(去 protocol + path)给 LLM 一眼看清
            url = info["top_url"]
            try:
                host = url.split("//", 1)[1].split("/", 1)[0]
            except IndexError:
                host = url
            t = (info["top_url_title"] or "").strip()
            if t:
                # 截 30 字防 prompt 膨胀 + 防 LLM 模仿冗长 title
                t_short = t[:30] + ("…" if len(t) > 30 else "")
                line += (
                    f"(主要看 {host} {t_short} "
                    f"{_fmt_duration_zh(info['top_url_seconds'])})"
                )
            else:
                line += (
                    f"(主要在 {host} "
                    f"{_fmt_duration_zh(info['top_url_seconds'])})"
                )
        lines.append(line)
    if recent_app:
        lines.append("")
        lines.append(f"最近 30 分钟主要在: {recent_app}")

    return "\n".join(lines)


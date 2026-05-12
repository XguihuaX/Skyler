"""v3.5 chunk 8a — activity-based smart trigger 决策层。

把 ``activity_watcher.ActivityChange`` 翻译成"要不要主动开口 + 哪条规则"。

设计要点
========

* **决策**：规则表 ``_RULES``，按 change.kind + change.detail 匹配 → 返
  trigger label 或 None
* **节流**：``_last_fire_per_label`` in-memory dict。同 label 距上次 < N
  分钟则 skip（N 默认 30，``config.activity_watcher.trigger_throttle_minutes``
  可调）
* **active-conversation guard**：最近 5 分钟有 user turn → skip（不打断用户
  正在聊的话）
* **daily cap**：每天最多 N 次 activity trigger（N 默认 5）。in-memory 计数
  跨午夜自动 reset
* **黑名单一票**：ActivityWatcher 已经把黑名单 app/URL 字段置 None；这里
  再补一道——active_app=None 时所有规则都不触发（除非 long_focus 已锁定
  了之前的 app 字段值，那是 latching 的特性）

Public API
==========

* ``activity_smart_handler(change: ActivityChange) -> None``
  async function；注册到 ``activity_watcher.register_change_listener``
* ``reset_state_for_test()``    清节流 + 计数器
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from backend.config import config_yaml
from backend.database import AsyncSessionLocal
from backend.database.models import ChatHistory
from backend.integrations.activity_watcher import ActivityChange

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------


def _cfg() -> dict:
    return (config_yaml.get("activity_watcher") or {})


def get_throttle_minutes() -> int:
    try:
        return max(1, int(_cfg().get("trigger_throttle_minutes", 30)))
    except (TypeError, ValueError):
        return 30


def get_max_daily_triggers() -> int:
    try:
        return max(0, int(_cfg().get("max_daily_triggers", 5)))
    except (TypeError, ValueError):
        return 5


def get_default_user_id() -> str:
    return str(config_yaml.get("default_user_id") or "default")


# ---------------------------------------------------------------------------
# 规则集
# ---------------------------------------------------------------------------


# 已知 IDE / 代码编辑器名（macOS NSWorkspace ``frontmostApplication.localizedName``
# 返值的 lower 形式匹配）。
#
# **hotfix-6 关键 fix**：macOS 上 VSCode 的 CFBundleName 是 ``"Code"``，NSWorkspace
# 返 ``"Code"`` 而**不是** ``"Visual Studio Code"``——这是 chunk 8a 默认列表的
# 漏网。用户切 VSCode 看不到 trigger 的根因就是这条。同步补全其他 IDE 的
# 实际 macOS localizedName（与品牌名经常不同）。
_IDE_APPS = {
    # VS Code 系列
    "code",                  # ⭐ macOS NSWorkspace 返这个（CFBundleName）
    "visual studio code",    # 极少数 build / 兼容
    "vscode",
    "code - insiders",       # VSCode Insiders
    "cursor",
    "windsurf",              # Codeium 编辑器
    "zed",
    # JetBrains 家族（macOS NSWorkspace 返带空格的 localizedName）
    "pycharm",
    "pycharm ce",
    "pycharm professional",
    "intellij idea",
    "intellij idea ce",
    "intellij idea ultimate",
    "phpstorm",
    "webstorm",
    "rubymine",
    "goland",
    "rider",
    "clion",
    "datagrip",
    "appcode",
    "fleet",
    "android studio",
    # Apple / 老牌编辑器
    "xcode",
    "sublime text",
    "atom",
    "nova",                  # Panic Nova
    "bbedit",
    "textmate",
    # 命令行 / 终端类（用户在终端里用 vim/emacs 也算）
    "neovim",
    "vim",
    "emacs",
    "macvim",
    # hotfix-8: macOS 自家 Terminal.app + 第三方终端
    # **中文 macOS i18n**: Apple 原生 app(Terminal.app)的 bundle 含 zh-Hans
    # lproj + localized CFBundleDisplayName='终端',NSWorkspace.frontmost
    # Application.localizedName 在中文 macOS 上返 ``"终端"`` 而非 ``"Terminal"``。
    # audit 真机验证: ``am.get_active_app()`` 返 ``'终端'``。
    # 第三方终端(iTerm2 / Alacritty / WezTerm / Warp / Kitty / Hyper)bundle
    # 无 zh lproj,在中文 macOS 仍返英文名。
    "terminal",
    "终端",          # ⭐ 中文 macOS Apple Terminal.app localizedName
    "iterm",
    "iterm2",
    "alacritty",
    "wezterm",
    "warp",
    "kitty",
    "hyper",
}

# 已知音乐 / 媒体 app
_MUSIC_APPS = {
    "spotify",
    "网易云音乐",
    "neteasemusic",
    "apple music",
    "music",          # macOS 自带 Apple Music app
    "qqmusic",
    "qq音乐",
    "youtube music",
}

# 技术文档 URL 模式（lower 子串匹配 hostname + path）
_TECH_DOC_URL_PATTERNS = [
    "docs.python.org",
    "developer.mozilla.org",
    "docs.rs",
    "react.dev",
    "vuejs.org",
    "docs.djangoproject.com",
    "fastapi.tiangolo.com",
    "tauri.app",
    "kubernetes.io/docs",
    "docs.github.com",
    "stackoverflow.com/questions",
    "realpython.com",
    "medium.com",
    "dev.to",
    # 教程域名 catch-all：含 ``/tutorial`` / ``/guide`` / ``/learn`` path
    "/tutorial",
    "/guide",
    "/learn",
    "/getting-started",
]


def _is_ide(app: Optional[str]) -> bool:
    return bool(app) and app.lower() in _IDE_APPS


def _is_music(app: Optional[str]) -> bool:
    return bool(app) and app.lower() in _MUSIC_APPS


def _is_tech_doc_url(url: Optional[str]) -> bool:
    if not url:
        return False
    u = url.lower()
    return any(p in u for p in _TECH_DOC_URL_PATTERNS)


def _is_late_night(ts: float) -> bool:
    """0-5 点视为深夜（按本地时区 ``datetime.now``）。"""
    return 0 <= datetime.fromtimestamp(ts).hour < 5


def _classify(change: ActivityChange) -> Optional[str]:
    """change → label string，or None 不触发。"""
    detail = change.detail or {}
    if change.kind == "app_changed":
        new_app = detail.get("new_app")
        if _is_ide(new_app):
            # 深夜 IDE 用专门 prompt（更温柔）
            if _is_late_night(change.new.timestamp):
                return "activity_late_night_ide"
            return "activity_ide_open"
        if _is_music(new_app):
            return "activity_music"
        return None
    if change.kind == "url_changed":
        if _is_tech_doc_url(detail.get("new_url")):
            return "activity_url_tech_doc"
        return None
    if change.kind == "app_focus_long":
        return "activity_long_focus"
    # url_dwell_long / doc_changed 暂不出 trigger（v1 保守）
    return None


# ---------------------------------------------------------------------------
# In-memory 节流 + daily counter
# ---------------------------------------------------------------------------


_last_fire_per_label: dict[str, float] = {}
_today_count = 0
_today_date: Optional[str] = None       # ISO date string in local tz
_state_lock = asyncio.Lock()


def _today_iso() -> str:
    return datetime.now().date().isoformat()


def _reset_daily_if_new_day() -> None:
    global _today_date, _today_count
    today = _today_iso()
    if _today_date != today:
        _today_date = today
        _today_count = 0


async def _active_conversation_recent(user_id: str, *, within_seconds: int = 300) -> bool:
    """最近 ``within_seconds`` 秒内有 ``role='user'`` 的 chat_history → True。"""
    threshold = datetime.now() - timedelta(seconds=within_seconds)
    async with AsyncSessionLocal() as session:
        stmt = (
            select(ChatHistory.id)
            .where(
                ChatHistory.user_id == user_id,
                ChatHistory.role == "user",
                ChatHistory.created_at >= threshold,
            )
            .limit(1)
        )
        row = (await session.execute(stmt)).first()
    return row is not None


from datetime import timedelta  # noqa: E402 — 放后避免 split import


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


async def activity_smart_handler(change: ActivityChange) -> None:
    """注册到 ActivityWatcher 的 listener。

    每次 ActivityWatcher 检测到 change 调一次；本函数负责"要不要走 + 走哪
    条"，过 4 道闸：
      1. classify → 拿 label，不命中规则直接 return
      2. active-conversation guard（最近 5 min 有 user turn → skip）
      3. throttle（同 label N 分钟内不重发）
      4. daily cap（一天最多 N 次 activity trigger）
    全过则实例化 ActivityProactiveTrigger + ``run_trigger(trigger, user_id)``。

    hotfix-6 INFO log 6 道：每道闸命中都 log 原因，让用户能从 backend.log
    自我诊断"为什么 app 切了 Momo 没说话"。
    """
    label = _classify(change)
    if label is None:
        # hotfix-6: 不命中规则的 change（如切到 Finder）也 INFO log 一次
        # 让用户知道 "watcher 跑了 + 看到了 change，只是没匹配任何 IDE/音乐/
        # 技术文档 规则"
        kind = change.kind
        if kind == "app_changed":
            logger.info(
                "[activity_smart] classify: matched=False kind=app_changed "
                "new_app=%r (not in IDE/music)",
                (change.detail or {}).get("new_app"),
            )
        elif kind == "url_changed":
            logger.info(
                "[activity_smart] classify: matched=False kind=url_changed "
                "new_url=%s (not a known tech-doc pattern)",
                (change.detail or {}).get("new_url"),
            )
        else:
            logger.info(
                "[activity_smart] classify: matched=False kind=%s", kind,
            )
        return

    logger.info(
        "[activity_smart] classify: matched=True kind=%s label=%s",
        change.kind, label,
    )

    user_id = get_default_user_id()

    # 2) 活跃对话守护：用户刚跟 Momo 聊过 → 不主动插话
    try:
        active = await _active_conversation_recent(user_id, within_seconds=300)
    except Exception as exc:
        # 数据库异常吞掉，倾向"宁可不发"（active=True 当 fail-safe）
        logger.warning("[activity_smart] active-conversation check failed: %s; skip", exc)
        return
    if active:
        # hotfix-6: 明确 reason 让用户知道 5 min 内有 user turn
        logger.info(
            "[activity_smart] skipped: reason=active_conversation label=%s "
            "(用户最近 5 分钟内有 user 发言，主动 trigger 让位)",
            label,
        )
        return

    async with _state_lock:
        # 3) 节流
        now = time.time()
        last = _last_fire_per_label.get(label, 0.0)
        throttle_sec = get_throttle_minutes() * 60
        if now - last < throttle_sec:
            remaining = int((throttle_sec - (now - last)) / 60)
            # hotfix-6: 加 last_fired ISO 时间戳让用户看到具体在 throttle 啥
            last_iso = datetime.fromtimestamp(last).strftime("%H:%M:%S") if last else "—"
            logger.info(
                "[activity_smart] throttled: label=%s last_fired=%s "
                "remaining=%d min (config trigger_throttle_minutes=%d)",
                label, last_iso, remaining, get_throttle_minutes(),
            )
            return

        # 4) daily cap
        _reset_daily_if_new_day()
        cap = get_max_daily_triggers()
        if cap > 0 and _today_count >= cap:
            logger.info(
                "[activity_smart] skipped: reason=daily_cap label=%s "
                "today=%d/%d (config max_daily_triggers=%d)",
                label, _today_count, cap, cap,
            )
            return

        # 通过四道闸，记账
        _last_fire_per_label[label] = now
        globals()["_today_count"] = _today_count + 1
        # hotfix-6: 与"skipped"系列同步 reason= 风格，统一 grep 路径
        logger.info(
            "[activity_smart] proactive trigger fired: label=%s "
            "count_today=%d/%d user_id=%s",
            label, _today_count + 1, cap if cap > 0 else 999, user_id,
        )

    # 出锁后异步触发，run_trigger 自己会 spawn / push WS
    try:
        from backend.proactive.engine import run_trigger
        from backend.proactive.triggers.activity import ActivityProactiveTrigger
        trigger = ActivityProactiveTrigger(label=label, detail=change.detail)
        await run_trigger(trigger, user_id=user_id)
        # hotfix-6: run_trigger 内部走完 ChatAgent + WS push + 入库链；INFO 一条
        # "send-complete" 让用户能区分"trigger 决策"与"实际 ChatAgent 走完"
        logger.info(
            "[activity_smart] proactive trigger sent: label=%s (ChatAgent 已走完，WS 已 push)",
            label,
        )
    except Exception as exc:
        logger.warning(
            "[activity_smart] run_trigger failed for %s: %s", label, exc,
        )


def reset_state_for_test() -> None:
    """**测试专用**。"""
    global _today_count, _today_date
    _last_fire_per_label.clear()
    _today_count = 0
    _today_date = None

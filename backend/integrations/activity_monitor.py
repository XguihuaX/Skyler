"""v3.5 chunk 8a — 系统活动状态查询（active app / browser tab / document path）。

设计要点
========

* **macOS 主路径**：
  - active app 走 ``AppKit.NSWorkspace.frontmostApplication``（pyobjc 已是
    EventKit transitive 依赖；与 chunk 3a clipboard 同源）
  - 浏览器 tab 走 ``osascript`` AppleScript 子进程（subprocess.run，timeout
    2s 防卡）。无 Chrome / Safari 启动时 AppleScript 返空 → 我们返 None
  - frontmost document 同样走 AppleScript（Word / Pages 支持 ``document of
    front window``）
* **跨平台**：非 macOS / pyobjc 缺失 / osascript 缺失 → 所有函数返 None。
  调用方按 None 走 graceful 路径，决不能抛错让 ActivityWatcher / capability
  阻塞主对话（与 chunk 3a / chunk 6b 一致）
* **零网络**：本 module 不联网、不读浏览器历史、不解析页面正文。仅暴露
  "你在用什么 / 看哪个 URL / 打开什么本地文件" 元数据。URL 内容 fetch
  在 ``url_fetcher.py`` 单独承担

Public API
==========

* ``get_active_app() -> Optional[str]``
* ``get_chrome_active_tab() -> Optional[tuple[str, str]]`` (url, title)
* ``get_safari_active_tab() -> Optional[tuple[str, str]]``
* ``get_browser_url() -> Optional[tuple[str, str, str]]`` (browser, url, title)
  — **frontmost-gated**(hotfix-9):browser 必须是 frontmost macOS app 才返
  非 None;否则后台 Chrome/Safari 仍打开 bilibili 时 stay_timer 会把不在
  视野内的 URL 算作当前活动 → 误触发 chunk 8a-ext judge
* ``get_active_document_path() -> Optional[tuple[str, str]]`` (path, app_kind)
* ``IS_MACOS`` 平台 flag
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"

# pyobjc NSWorkspace 仅 macOS 有；其他平台 import 会失败，是预期 fallback 路径
_NSWorkspace = None
if IS_MACOS:
    try:
        from AppKit import NSWorkspace  # type: ignore

        _NSWorkspace = NSWorkspace
    except Exception as exc:  # pragma: no cover - 真 pyobjc 装好时不走这里
        logger.warning(
            "[activity_monitor] AppKit.NSWorkspace import failed: %s", exc,
        )


_OSASCRIPT_TIMEOUT_SECONDS = 2.0


# ---------------------------------------------------------------------------
# osascript helper
# ---------------------------------------------------------------------------


def _run_osascript(script: str) -> Optional[str]:
    """跑一段 AppleScript，返 stdout 字符串。失败 / 超时 / 非 macOS → None。

    osascript 退出码非 0 时常见原因：
      * 用户未授权（"Allow Skyler to control X" 系统弹窗未点）
      * 目标 app（Chrome / Safari）未启动
      * Script 语法不对（开发期）

    任一情况均不抛错，silently 返 None 让上层走 None-fallback。
    """
    if not IS_MACOS:
        return None
    if shutil.which("osascript") is None:  # pragma: no cover - macOS 总是有
        return None
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_OSASCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[activity_monitor] osascript timed out (>%ss)",
                       _OSASCRIPT_TIMEOUT_SECONDS)
        return None
    except Exception as exc:  # pragma: no cover - subprocess 异常极少见
        logger.warning("[activity_monitor] osascript failed: %s", exc)
        return None
    if res.returncode != 0:
        # stderr 是英文 + 含"Not authorized"等关键字时给一点 hint，但不抛
        stderr = (res.stderr or "").strip()
        if stderr:
            logger.debug("[activity_monitor] osascript rc=%s: %s",
                         res.returncode, stderr[:200])
        return None
    return (res.stdout or "").strip()


# ---------------------------------------------------------------------------
# Active app
# ---------------------------------------------------------------------------


def get_active_app() -> Optional[str]:
    """当前 frontmost app 的 ``localizedName``（如 ``"Google Chrome"`` /
    ``"Visual Studio Code"`` / ``"Spotify"``）。

    走 NSWorkspace 直查；非 macOS / pyobjc 缺失 / 极端 None → 返 None。
    与 osascript 路径**不混用**——NSWorkspace 在 sandbox 内就能跑，不需要
    AppleEvent 权限弹窗，比 ``tell application "System Events" to get name
    of first application process whose frontmost is true`` 体验干净一档。
    """
    if not IS_MACOS or _NSWorkspace is None:
        return None
    try:
        ws = _NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication()
        if app is None:
            return None
        name = app.localizedName()
        if not name:
            return None
        return str(name)
    except Exception as exc:  # pragma: no cover - pyobjc 内部异常少见
        logger.warning("[activity_monitor] get_active_app failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Browser tabs
# ---------------------------------------------------------------------------


def _parse_url_title(raw: Optional[str]) -> Optional[Tuple[str, str]]:
    """AppleScript 返 ``URL{TAB_SEP}Title`` 二段；解析成 (url, title)。

    上层 script 用 ASCII char 30（``\\u001e`` "record separator"）做分隔，
    title 含 `\\n` / `\\t` / 逗号等情况下也能解析。
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if "" not in raw:
        # 老脚本 / 异常输出 fallback：以第一个 tab 为分隔
        if "\t" in raw:
            url, title = raw.split("\t", 1)
            return url.strip(), title.strip()
        # 只拿到 URL 也算可用结果
        return raw, ""
    url, title = raw.split("", 1)
    return url.strip(), title.strip()


_CHROME_SCRIPT = """
on jsonish(s)
    return s
end jsonish

set theSep to (ASCII character 30)
try
    tell application "Google Chrome"
        if not (exists window 1) then return ""
        set theURL to URL of active tab of window 1
        set theTitle to title of active tab of window 1
        return theURL & theSep & theTitle
    end tell
on error
    return ""
end try
"""


_SAFARI_SCRIPT = """
set theSep to (ASCII character 30)
try
    tell application "Safari"
        if not (exists window 1) then return ""
        set theURL to URL of current tab of window 1
        set theTitle to name of current tab of window 1
        return theURL & theSep & theTitle
    end tell
on error
    return ""
end try
"""


def get_chrome_active_tab() -> Optional[Tuple[str, str]]:
    """Chrome 当前 window 的 active tab (url, title)。

    Chrome 未启动 / 没窗口 / 用户未授予 AppleEvent 权限 → None。
    Brave / Arc / Chromium fork 共享 Chrome 的 AppleScript dictionary 但走
    不同 application id；这一版只覆盖原生 Chrome，brave / arc 后续 backlog。
    """
    raw = _run_osascript(_CHROME_SCRIPT)
    return _parse_url_title(raw)


def get_safari_active_tab() -> Optional[Tuple[str, str]]:
    """Safari 当前 window 的 current tab (url, title)。

    Safari 未启动 / 没窗口 / 用户未授予权限 → None。
    """
    raw = _run_osascript(_SAFARI_SCRIPT)
    return _parse_url_title(raw)


# ---------------------------------------------------------------------------
# v3.5 hotfix-9 — frontmost-gated browser URL
#
# 问题:``get_chrome_active_tab`` / ``get_safari_active_tab`` 的 AppleScript
# 只要 Chrome/Safari 在跑且有窗口就返 active tab,不查"那个浏览器是不是
# frontmost macOS app"。结果:
#   * 用户早上看 bilibili,中午切到 VSCode 写代码
#   * Chrome 窗口在后台,active tab 仍是 bilibili
#   * ``get_chrome_active_tab`` 返 bilibili URL → ``snapshot.browser`` 把
#     不在视野内的 URL 塞进 state → stay_timer 累积 → 5 min 后 8a-ext
#     judge 看到"停 bilibili 5 min" → Momo 主动聊招聘 → 用户体验崩塌
#
# 修法:在 activity_monitor 层包一层 ``get_browser_url``,先 call
# ``get_active_app()`` 拿 frontmost localizedName,在 ``_BROWSER_APPS``
# 集合命中才路由到对应 AppleScript;否则返 None,上层 watcher/capability
# 自然 fallback 到 app stay。
#
# 选 activity_monitor 层包,而不是 AppleScript 内嵌"frontmost of system
# events" check:后者需要 Accessibility 权限(NSApplications 权限之外,
# 又是一道弹窗),不够干净。NSWorkspace.frontmostApplication 不要任何
# 额外权限,与 chunk 8a ``get_active_app`` 同源。
# ---------------------------------------------------------------------------


# 常见浏览器 localizedName(小写、含中英文 alias)。hotfix-8 教训:Apple 原生
# bundle 有 zh-Hans lproj → Safari 中文 macOS 仍返 "Safari"(Safari 是品牌
# 不被本地化,跟 Spotify 一样);第三方浏览器 bundle 不带 zh lproj 中文系统
# 仍返英文名。所以中文 alias 对几乎所有浏览器都是冗余,但保留作 defensive
# 防御未来某个 fork 真的本地化(成本极低)。
_BROWSER_APPS: frozenset = frozenset({
    # Chromium 系列
    "google chrome", "chrome", "google chrome 浏览器",
    "google chrome canary", "chromium",
    "microsoft edge", "edge", "microsoft edge 浏览器",
    "brave browser", "brave",
    "arc",
    "vivaldi",
    "opera", "opera gx",
    # WebKit
    "safari", "safari 浏览器",
    "safari technology preview",
    # Gecko
    "firefox", "firefox 浏览器",
    "firefox developer edition", "firefox nightly",
})


def get_browser_url() -> Optional[Tuple[str, str, str]]:
    """**frontmost-gated** browser tab info。

    返:
      * ``(browser, url, title)`` —— frontmost 是已支持的浏览器且 URL 可拿
        ``browser ∈ {"chrome", "safari"}``(当前只有这两个有 AppleScript impl)
      * ``None`` —— frontmost 不是浏览器 / 浏览器无 active window / AppleScript
        失败 / 非 macOS

    hotfix-9: 解决 chunk 8a"backgrounded Chrome URL 仍被 watcher 当成 active
    stay"问题。其他浏览器(Firefox/Edge/Arc/Brave 等)目前无 AppleScript 实现,
    即便 frontmost 也返 None(用户在 Firefox 时 stay tracking 走 app:Firefox,
    与 hotfix-9 前行为一致 — 真正变化的只有 Chrome/Safari 后台时的误报路径)。

    与 ``get_chrome_active_tab`` / ``get_safari_active_tab`` 的关系:
      * 它们仍是 raw primitives(无 frontmost check)— 保留作内部工具 + 既有
        测试不破
      * ``get_browser_url`` 是高层语义(策略 = 浏览器必须是 frontmost)— 所有
        "用户当前在看什么 URL"的调用点都该走这个
    """
    active = get_active_app()
    if active is None:
        return None
    if active.strip().lower() not in _BROWSER_APPS:
        return None
    active_lower = active.lower()
    # 路由到 AppleScript:目前只 Chrome 系 + Safari 系有实现
    if "chrome" in active_lower or "chromium" in active_lower:
        tab = get_chrome_active_tab()
        if tab is None:
            return None
        url, title = tab
        return ("chrome", url, title)
    if "safari" in active_lower:
        tab = get_safari_active_tab()
        if tab is None:
            return None
        url, title = tab
        return ("safari", url, title)
    # Firefox / Edge / Arc / Brave / Vivaldi / Opera: 识别但无 AppleScript
    # impl —— 返 None(上层走 app stay),与 hotfix-9 前用户体验一致
    return None


# ---------------------------------------------------------------------------
# Active document
# ---------------------------------------------------------------------------


_DOC_SCRIPT_TEMPLATE = """
try
    tell application "{app}"
        if not (exists document 1) then return ""
        set p to path of document 1
        return p
    end tell
on error
    return ""
end try
"""

# 顺序优先：先问 Word 再问 Pages —— Word 用户群更大；Pages 不常用
_DOC_APPS = [
    ("Microsoft Word", "word"),
    ("Pages",          "pages"),
]


def get_active_document_path() -> Optional[Tuple[str, str]]:
    """frontmost Word / Pages 文档路径 + 类型 tag。

    优先查 active app 名是否在 _DOC_APPS 列表里，是的话直接问该 app；
    否则按 _DOC_APPS 顺序探。两类 app 都 silent 时返 None。

    返 ``(path, app_kind)``：
      app_kind ∈ ``{"word", "pages"}``，让 capability 层决定如何读内容
      （chunk 7 ``docx.read`` 对 word，Pages 暂只暴露 path）。
    """
    if not IS_MACOS:
        return None
    active = get_active_app()
    # 把 active app 推到队首（如果正巧是 Word / Pages，能少跑一次 osascript）
    apps = list(_DOC_APPS)
    if active:
        for i, (app_name, _) in enumerate(apps):
            if app_name == active and i != 0:
                apps.insert(0, apps.pop(i))
                break
    for app_name, kind in apps:
        path = _run_osascript(_DOC_SCRIPT_TEMPLATE.format(app=app_name))
        if path:
            return path, kind
    return None


# ---------------------------------------------------------------------------
# v3.5 chunk 8a-ext V2: macOS 用户活跃度(键鼠 idle 秒数)
#
# 用 ``ioreg -c IOHIDSystem`` 子进程拿 ``HIDIdleTime`` IORegistry 字段(纳秒)
# / 1e9 转秒。Quartz API (``CGEventSourceSecondsSinceLastEventType``) 是
# 等价路径但需要 ``pyobjc-framework-Quartz`` 新 pip 包,本 commit 复用 chunk
# 8a 既有 subprocess 模式零新依赖。
#
# 用例: ActivityJudge 慢路径在 LLM call 之前检查 user idle 秒数,长时间静止
# (默 300s)→ 认为人不在电脑前,skip judge 不打扰。
# ---------------------------------------------------------------------------


_IOREG_TIMEOUT_SECONDS = 2.0
_HID_IDLE_RE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


def get_idle_seconds() -> Optional[float]:
    """查自上次键鼠活动以来的秒数。

    macOS: 跑 ``ioreg -c IOHIDSystem`` + 正则抽 ``HIDIdleTime`` 纳秒 / 1e9。
    非 macOS / ioreg 缺失 / 异常 / 解析失败 → 返 None(调用方按 None
    走 fallback "用户活跃"路径,不破坏 V1 行为)。

    实测真机:
      ``$ ioreg -c IOHIDSystem | grep HIDIdleTime``
      ``      "HIDIdleTime" = 146795750``    ← 0.147s

    HIDIdleTime 字段是 macOS 10.4+ IORegistry 标准,稳定不会变。
    """
    if not IS_MACOS:
        return None
    if shutil.which("ioreg") is None:  # pragma: no cover - macOS 总是有
        return None
    try:
        res = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=_IOREG_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[activity_monitor] ioreg timed out (>%ss)",
                       _IOREG_TIMEOUT_SECONDS)
        return None
    except Exception as exc:  # pragma: no cover - subprocess 异常极少
        logger.warning("[activity_monitor] ioreg failed: %s", exc)
        return None
    if res.returncode != 0:
        logger.debug(
            "[activity_monitor] ioreg rc=%s stderr=%r",
            res.returncode, (res.stderr or "")[:200],
        )
        return None
    m = _HID_IDLE_RE.search(res.stdout or "")
    if not m:
        # 极端情况: 系统不输出 HIDIdleTime(改 macOS 版本 / SIP 限制 / 等)
        logger.debug(
            "[activity_monitor] HIDIdleTime regex no match in ioreg output"
        )
        return None
    try:
        ns = int(m.group(1))
    except (ValueError, IndexError):  # pragma: no cover - regex 抓到就一定数字
        return None
    return ns / 1e9

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
* ``get_active_document_path() -> Optional[tuple[str, str]]`` (path, app_kind)
* ``IS_MACOS`` 平台 flag
"""
from __future__ import annotations

import logging
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

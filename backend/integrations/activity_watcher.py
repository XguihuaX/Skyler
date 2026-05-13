"""v3.5 chunk 8a — 后台 ActivityWatcher。

按 ``poll_interval_seconds`` 周期 sniff 当前活动状态（active app / 浏览器 tab
/ frontmost document），检测显著变化并触发 callback。callback 由 commit 5
``smart_trigger`` 注入，本 module 不知道 callback 内部业务（与 chunk 10
extractor / chunk 3a clipboard 一样的"layered async polling task"模式）。

设计原则
========

* **lifecycle 对齐 chunk 10 extractor**：``asyncio.create_task(run_loop)`` +
  ``stop_event`` + ``stop()`` 5s timeout 兜底
* **任意 step 异常 → log + 不阻塞**：snapshot 失败 / callback 失败 / 网络
  抖动 都不能让 watcher 自杀。整 ``run_loop`` 包 try-except，下一拍正常继续
* **黑名单一票**：blocked_apps / blocked_url_patterns 命中 → 把字段清掉
  再写入 last_state，让 trigger 看不到敏感场景
* **disabled 友好**：``config.activity_watcher.enabled=false`` → watcher 不
  启动；运行中也可 ``set_enabled(False)`` 暂停 loop（保留单例 + 后续重启）

Public API
==========

* ``activity_watcher`` 单例
* ``ActivityWatcher.start_polling()`` / ``stop_polling()``
* ``ActivityWatcher.snapshot() -> ActivityState``    一次同步快照
* ``ActivityWatcher.get_last_state() -> Optional[ActivityState]``
* ``ActivityWatcher.register_change_listener(fn)``   commit 5 装载 smart
  trigger 的入口

ActivityState
=============

* ``active_app: Optional[str]``
* ``browser: Optional[{browser, url, title}]``
* ``document: Optional[{path, type, basename}]``
* ``url_content: Optional[{title, content}]``  当 fetch_url_content=True 且
  URL 新切且非黑名单时 best-effort 异步抓取
* ``timestamp: float`` epoch 秒
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable, List, Optional

from backend.config import config_yaml
from backend.integrations import activity_monitor as _am
from backend.integrations import url_fetcher as _uf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------


def _cfg() -> dict:
    return (config_yaml.get("activity_watcher") or {})


def get_enabled() -> bool:
    val = _cfg().get("enabled", False)
    return bool(val)


def get_poll_interval_seconds() -> int:
    try:
        return max(5, int(_cfg().get("poll_interval_seconds", 30)))
    except (TypeError, ValueError):
        return 30


def get_fetch_url_content() -> bool:
    return bool(_cfg().get("fetch_url_content", True))


def get_blocked_apps() -> list[str]:
    raw = _cfg().get("blocked_apps") or []
    return [str(x) for x in raw]


def get_blocked_url_patterns() -> list[str]:
    raw = _cfg().get("blocked_url_patterns") or _uf.DEFAULT_BLOCKED_PATTERNS
    return [str(x) for x in raw]


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------


@dataclass
class ActivityState:
    active_app: Optional[str] = None
    browser: Optional[dict] = None          # {browser, url, title}
    document: Optional[dict] = None         # {path, type, basename}
    url_content: Optional[dict] = None      # {title, content}
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ActivityChange:
    """两次 snapshot 间的差异。trigger 决策（commit 5）按 ``kind`` 分支。"""
    kind: str                 # 'app_changed' / 'url_changed' / 'doc_changed' /
                              # 'app_focus_long' / 'url_dwell_long'
    old: Optional[ActivityState]
    new: ActivityState
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ActivityWatcher
# ---------------------------------------------------------------------------


_ListenerFn = Callable[[ActivityChange], Awaitable[None]]
# chunk 8a-ext: poll listener — 每 poll 触发,接 ActivityState(可读 stay 时长)
_PollListenerFn = Callable[["ActivityState"], Awaitable[None]]


class ActivityWatcher:
    """单例后台 watcher。``start_polling`` 起 task，``stop_polling`` cancel。"""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._enabled_override: Optional[bool] = None
        self._last_state: Optional[ActivityState] = None
        self._app_focus_start: float = 0.0   # 当前 active_app 开始时间
        self._url_dwell_start: float = 0.0   # 当前 URL 开始时间
        self._listeners: List[_ListenerFn] = []
        # chunk 8a-ext: poll listeners 每 poll 触发(不依赖 change),让
        # ActivityJudge 慢路径每 tick 检查 stay duration + maybe judge。
        self._poll_listeners: List["_PollListenerFn"] = []

    # -- listeners -----------------------------------------------------------

    def register_change_listener(self, fn: _ListenerFn) -> None:
        """挂一个 async ``fn(ActivityChange) -> None`` 回调。

        watcher 每检测到 change 都按注册顺序串行调（不并发，避免 race），单
        callback 异常吞 + log 不影响后续。
        """
        if fn not in self._listeners:
            self._listeners.append(fn)

    def register_poll_listener(self, fn: "_PollListenerFn") -> None:
        """chunk 8a-ext: 挂一个 async ``fn(ActivityState) -> None`` poll 回调。

        与 ``register_change_listener`` 区别: poll listener 每 poll 都触发
        (无论是否有 change),让 ActivityJudge 慢路径能定期检查 stay duration
        + maybe judge。单 callback 异常吞 + log 不影响 watcher 主 loop。
        """
        if fn not in self._poll_listeners:
            self._poll_listeners.append(fn)

    def clear_listeners(self) -> None:
        self._listeners.clear()
        self._poll_listeners.clear()

    # -- lifecycle -----------------------------------------------------------

    def is_enabled(self) -> bool:
        """运行时优先 ``set_enabled`` 临时开关，否则走 config 默认。"""
        if self._enabled_override is not None:
            return self._enabled_override
        return get_enabled()

    def set_enabled(self, enabled: bool) -> None:
        """SettingsPanel toggle 调用。运行时 override，不写 config。

        从 True → False：cancel polling task；下次 start_polling 又起。
        """
        self._enabled_override = bool(enabled)
        if not enabled and self._task is not None and not self._task.done():
            self._stop_event.set()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start_polling(self) -> None:
        """lifespan 调。若 disabled 或 task 已在跑，no-op。"""
        if self._task is not None and not self._task.done():
            return
        if not self.is_enabled():
            logger.info("[activity] watcher disabled by config")
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self.run_loop())
        logger.info(
            "[activity] watcher started interval=%ds fetch_url=%s",
            get_poll_interval_seconds(), get_fetch_url_content(),
        )

    async def stop_polling(self) -> None:
        """优雅关停：set stop_event → 等 ≤ 5s → cancel 兜底。"""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("[activity] watcher did not stop in 5s, cancelling")
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            self._task = None
            logger.info("[activity] watcher stopped")

    # -- snapshot -----------------------------------------------------------

    async def snapshot(self, *, with_url_content: Optional[bool] = None) -> ActivityState:
        """一次 sniff。黑名单字段直接置 None（不让 listeners 看到敏感场景）。

        ``with_url_content=None`` 走 config 默认；显式 True/False 覆盖。本同步
        sniff 不抓 URL 内容（默认）；URL 内容抓在 ``_on_url_change`` 异步走
        （让 snapshot 本身 < 100ms 完成）。
        """
        blocked_apps = set(get_blocked_apps())
        blocked_urls = get_blocked_url_patterns()

        app = _am.get_active_app()
        if app is not None and app in blocked_apps:
            app = None  # 黑名单 app → 上层看到 None 不触发

        # hotfix-9: 走 frontmost-gated get_browser_url 而不是直接 chrome/safari
        # raw primitives — Chrome/Safari 在后台时它们 AppleScript 仍返 active tab
        # (e.g. 早上看的 bilibili)导致 stay_timer 累积错误的 URL。get_browser_url
        # 在 activity_monitor 层先 check frontmost,非浏览器 frontmost → None。
        browser_dict: Optional[dict] = None
        binfo = _am.get_browser_url()
        if binfo is not None:
            browser_name, url, title = binfo
            if not _uf.is_url_blocked(url, blocked_urls):
                browser_dict = {"browser": browser_name, "url": url, "title": title}

        doc_info = _am.get_active_document_path()
        doc_dict: Optional[dict] = None
        if doc_info is not None:
            path, kind = doc_info
            doc_dict = {"path": path, "type": kind,
                        "basename": _basename(path)}

        return ActivityState(
            active_app=app,
            browser=browser_dict,
            document=doc_dict,
            url_content=None,
            timestamp=time.time(),
        )

    # -- change detection ---------------------------------------------------

    def _detect_changes(
        self,
        old: Optional[ActivityState],
        new: ActivityState,
        *,
        now: float,
    ) -> List[ActivityChange]:
        """对比 old vs new + 累积时长，返 0..N 个 ActivityChange。"""
        out: List[ActivityChange] = []

        # 1) app_changed
        old_app = old.active_app if old else None
        new_app = new.active_app
        if new_app != old_app:
            self._app_focus_start = now
            out.append(ActivityChange(
                kind="app_changed", old=old, new=new,
                detail={"old_app": old_app, "new_app": new_app},
            ))
        else:
            # 长 focus（同 app 持续 > 90 分钟，commit 5 可读 detail）
            if (new_app is not None and self._app_focus_start >= 0
                    and (now - self._app_focus_start) > _LONG_FOCUS_SECONDS):
                # 仅在跨过阈值的那一拍触发；触发后把 _app_focus_start 抹掉
                # 强制下一次 app_changed 才能再次跨阈
                out.append(ActivityChange(
                    kind="app_focus_long", old=old, new=new,
                    detail={"app": new_app,
                            "focus_seconds": int(now - self._app_focus_start)},
                ))
                self._app_focus_start = -1.0

        # 2) url_changed (only when same browser type)
        old_url = (old.browser or {}).get("url") if old else None
        new_url = (new.browser or {}).get("url") if new else None
        if new_url != old_url:
            self._url_dwell_start = now if new_url else 0.0
            if new_url is not None:
                out.append(ActivityChange(
                    kind="url_changed", old=old, new=new,
                    detail={"old_url": old_url, "new_url": new_url,
                            "title": (new.browser or {}).get("title", "")},
                ))
        else:
            if (new_url is not None and self._url_dwell_start >= 0
                    and (now - self._url_dwell_start) > _LONG_DWELL_SECONDS):
                out.append(ActivityChange(
                    kind="url_dwell_long", old=old, new=new,
                    detail={"url": new_url,
                            "title": (new.browser or {}).get("title", ""),
                            "dwell_seconds": int(now - self._url_dwell_start)},
                ))
                self._url_dwell_start = -1.0

        # 3) doc_changed
        old_path = (old.document or {}).get("path") if old else None
        new_path = (new.document or {}).get("path") if new else None
        if new_path != old_path and new_path is not None:
            out.append(ActivityChange(
                kind="doc_changed", old=old, new=new,
                detail={"old_path": old_path, "new_path": new_path,
                        "doc_type": (new.document or {}).get("type")},
            ))

        return out

    # -- url content best-effort -------------------------------------------

    async def _maybe_fetch_url_content(self, new_url: str) -> Optional[dict]:
        if not get_fetch_url_content():
            return None
        result = await _uf.fetch_article_content(
            new_url,
            blocked_patterns=get_blocked_url_patterns(),
            max_chars=5000,
        )
        if result and result.get("fetched"):
            return {"title": result.get("title", ""),
                    "content": result.get("content", "")}
        return None

    # -- run_loop ----------------------------------------------------------

    async def run_loop(self) -> None:
        """主 loop。每 ``poll_interval_seconds`` sniff + 判 change + dispatch
        listeners。任一 step 异常吞 + 下一拍正常继续。

        hotfix-6 INFO log 三档：
          * ``app detected``    每拍都 log 一次（让用户能在 backend.log 看到
                                "watcher 真的在 tick + sniff 到了 X"）
          * ``app changed``     检测到变化时 log（让用户能从 log 看到 chunk 8a
                                确实识别到了 app/url 切换）
          * listener 错误 / tick 异常 / url fetch 失败 各有 warning
        """
        tick_count = 0
        while not self._stop_event.is_set():
            try:
                state = await self.snapshot()
                tick_count += 1
                now = state.timestamp
                # hotfix-6 INFO #1: 每拍 sniff 结果
                browser_url = (state.browser or {}).get("url") if state.browser else None
                logger.info(
                    "[activity] app detected: tick=%d app=%r url=%s",
                    tick_count, state.active_app, browser_url or "—",
                )
                changes = self._detect_changes(self._last_state, state, now=now)
                # hotfix-6 INFO #2: 检测到的 change 列表（包括 kind + 关键 detail）
                if changes:
                    for c in changes:
                        if c.kind == "app_changed":
                            logger.info(
                                "[activity] app changed: from=%r to=%r",
                                c.detail.get("old_app"), c.detail.get("new_app"),
                            )
                        elif c.kind == "url_changed":
                            logger.info(
                                "[activity] url changed: to=%s title=%r",
                                c.detail.get("new_url"),
                                c.detail.get("title", "")[:60],
                            )
                        elif c.kind == "doc_changed":
                            logger.info(
                                "[activity] doc changed: to=%s",
                                c.detail.get("new_path"),
                            )
                        elif c.kind == "app_focus_long":
                            logger.info(
                                "[activity] app focus long: app=%r %ds",
                                c.detail.get("app"),
                                c.detail.get("focus_seconds", 0),
                            )
                        elif c.kind == "url_dwell_long":
                            logger.info(
                                "[activity] url dwell long: url=%s %ds",
                                c.detail.get("url"),
                                c.detail.get("dwell_seconds", 0),
                            )
                # URL 变了 + 配置允许抓 → best-effort 异步抓正文，结果直接挂在
                # state.url_content 上让下次 snapshot 看见（仅 attach 在本拍）
                for c in changes:
                    if c.kind == "url_changed":
                        new_url = c.detail.get("new_url")
                        if isinstance(new_url, str):
                            try:
                                state.url_content = await self._maybe_fetch_url_content(new_url)
                            except Exception as exc:
                                logger.warning(
                                    "[activity] url fetch failed: %s", exc,
                                )
                # dispatch listeners 串行
                for change in changes:
                    for fn in list(self._listeners):
                        try:
                            await fn(change)
                        except Exception as exc:
                            # hotfix-6: warning 而非 debug —— listener 静默失败
                            # 是 chunk 8a "app 切了但 Momo 没消息" 类 bug 主因
                            logger.warning(
                                "[activity] listener %s failed on %s: %s",
                                getattr(fn, "__name__", "<anon>"), change.kind, exc,
                            )
                # chunk 8a-ext: poll listeners 每 poll 触发(无论是否 change),
                # 让 ActivityJudge 慢路径检查 stay duration + maybe judge。
                # 同样串行 + 异常吞 + 不阻塞下一拍。
                for fn in list(self._poll_listeners):
                    try:
                        await fn(state)
                    except Exception as exc:
                        logger.warning(
                            "[activity] poll_listener %s failed: %s",
                            getattr(fn, "__name__", "<anon>"), exc,
                        )
                self._last_state = state
            except Exception as exc:
                logger.warning("[activity] watch tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=get_poll_interval_seconds())
            except asyncio.TimeoutError:
                pass  # 正常 tick

    # -- introspection -----------------------------------------------------

    def get_last_state(self) -> Optional[ActivityState]:
        return self._last_state

    def get_current_stay_info(self) -> Optional[dict]:
        """chunk 8a-ext: 当前 stay 摘要,给 ActivityJudge 慢路径用。

        返 ``{"key": "url:<X>"|"app:<X>"|"none", "start_ts": float,
        "duration_seconds": float, "app": str|None, "url": str|None,
        "title": str}`` 或 None(无 last_state)。

        stay_key 优先 URL,无 URL 时 fall back app。两个时间游标
        ``_app_focus_start`` / ``_url_dwell_start`` 已由 _detect_changes 维护:
        - app 没变 → _app_focus_start 保留之前值
        - app 变了 → _app_focus_start = now (新 stay 开始)
        - URL 类似
        - latching off(``-1.0``)后视为 stay 仍在,start = max(focus_start, dwell_start)
          的兜底
        """
        state = self._last_state
        if state is None:
            return None
        import time as _time
        now = _time.time()
        url = (state.browser or {}).get("url") if state.browser else None
        title = (state.browser or {}).get("title", "") if state.browser else ""
        app = state.active_app
        # 优先 URL stay,URL 是更细粒度的"用户在做什么"信号
        if url and self._url_dwell_start > 0:
            return {
                "key": f"url:{url}",
                "start_ts": self._url_dwell_start,
                "duration_seconds": max(0.0, now - self._url_dwell_start),
                "app": app,
                "url": url,
                "title": title,
            }
        if app and self._app_focus_start > 0:
            return {
                "key": f"app:{app}",
                "start_ts": self._app_focus_start,
                "duration_seconds": max(0.0, now - self._app_focus_start),
                "app": app,
                "url": url,
                "title": title,
            }
        return None


_LONG_FOCUS_SECONDS = 90 * 60     # 90 分钟同 app
_LONG_DWELL_SECONDS = 20 * 60     # 20 分钟同 URL


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1] if path else ""


# ---------------------------------------------------------------------------
# Permission self-check（commit 7）
# ---------------------------------------------------------------------------


async def check_macos_permissions() -> dict:
    """启动时一次性自检：NSWorkspace 能不能拿到 frontmost / AppleScript 能不能
    探到 Chrome / Safari。

    返 ``{ns_workspace_ok, applescript_ok, hint}``。前端首次启动应该在
    ``ns_workspace_ok=true`` 但 ``applescript_ok=false`` 时弹"需要授权 Skyler
    访问系统状态" + [打开系统设置] 跳转。
    """
    ns_ok = _am.get_active_app() is not None
    # 用一段不依赖具体 app 是否启动的 AppleScript 验权限：``return "ok"`` 总
    # 该成功；权限未授予会被 macOS 系统层拦截
    test = _am._run_osascript('return "ok"')
    applescript_ok = (test == "ok")
    hint = None
    if not ns_ok:
        hint = "macOS NSWorkspace 不可用（非 macOS 或 pyobjc 缺失）"
    elif not applescript_ok:
        hint = (
            "AppleScript 调用失败：可能是首次启动未授权。"
            "前往 系统设置 → 隐私与安全性 → 自动化，允许 Skyler 控制"
            "「Google Chrome」/「Safari」/「Microsoft Word」/「Pages」。"
        )
    return {
        "ns_workspace_ok": ns_ok,
        "applescript_ok": applescript_ok,
        "hint": hint,
    }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


activity_watcher = ActivityWatcher()


def reset_for_test() -> None:
    """**测试专用**。"""
    global activity_watcher
    activity_watcher = ActivityWatcher()

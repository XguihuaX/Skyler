"""2026-06-15 batch 2 [browser_login] · 浏览器扫码登录子进程管理器。

适用 server:小红书(xhs)等 Playwright 扫码登录服务 · 不走 env_required 凭证
modal · 改走"开浏览器扫码 → 存 cookie → 后续 holder 直接读 cookie"。

entry schema:
    xhs:
      transport: stdio
      command: npx
      args: [-y, xhs-mcp-server]
      auth: browser_login                 # 标识此 entry 走浏览器登录流
      login_command: npx                  # 开登录子进程的 command
      login_args:                          # args(通常跟 command/args 不同 · 进 login 模式)
      - -y
      - xhs-mcp-server
      - login
      cookie_path: ~/.skyler/xhs.json     # 存的 cookie 路径 · holder 读这条
      dangerous_tools: [publish_note, ...]

API(routes/mcp_api.py 接):
    POST /api/mcp/clients/{name}/login    启动登录子进程 · 立即返 task_id
    GET  /api/mcp/clients/{name}/login    轮询状态 · 返 status + cookie 是否就位

状态机:
    no_task              login 没启 / 子进程结束
    running              子进程在跑(浏览器开着扫码)
    cookie_ready         cookie 文件就位(login 子进程已结束)
    error                子进程异常 / 超时

不同步 hang:HTTP endpoint 拉子进程后立即返回 task_id · 子进程在 background
跑(asyncio.create_task) · 前端轮询 GET 查状态。enable holder 时不开浏览器 ·
只读 cookie 路径(若不存在 → enable 失败,提示用户先登录)。

cookie_path 解析:支持 ${HOME} / ~ 展开。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class _LoginTask:
    server_name: str
    cookie_path: Path
    proc: Optional[asyncio.subprocess.Process] = None
    status: str = "no_task"   # no_task / running / cookie_ready / error
    error: Optional[str] = None
    started_at: Optional[float] = None


# 单进程单用户 · 单 dict 足够
_login_tasks: dict[str, _LoginTask] = {}


def _expand_path(p: str) -> Path:
    """支持 ~ 和 ${VAR} 展开。"""
    return Path(os.path.expanduser(os.path.expandvars(p)))


def _resolve_cookie_path(conf: dict) -> Optional[Path]:
    raw = conf.get("cookie_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _expand_path(raw.strip())


def cookie_ready(conf: dict) -> bool:
    """holder ENTER 时调:cookie 文件是否就位 + 非空。

    False = 用户没登录或文件被删 · enable 时应该 raise 提示前端"先点登录"。
    """
    p = _resolve_cookie_path(conf)
    if p is None:
        return False
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


async def start_login(server_name: str, conf: dict) -> _LoginTask:
    """启动登录子进程 · 立即返 task(不 await 子进程结束)。

    幂等:已有 running task → 返既存(不重新开浏览器)。已有 cookie_ready /
    error → 起新一轮(重新登录场景)。
    """
    existing = _login_tasks.get(server_name)
    if existing is not None and existing.status == "running":
        return existing

    cookie_path = _resolve_cookie_path(conf)
    if cookie_path is None:
        task = _LoginTask(
            server_name=server_name, cookie_path=Path("/dev/null"),
            status="error", error="entry 缺 cookie_path 字段",
        )
        _login_tasks[server_name] = task
        return task

    login_command = conf.get("login_command")
    login_args = conf.get("login_args") or []
    if not login_command:
        task = _LoginTask(
            server_name=server_name, cookie_path=cookie_path,
            status="error", error="entry 缺 login_command 字段",
        )
        _login_tasks[server_name] = task
        return task

    # 命令存在性 check(早 fail)
    if shutil.which(login_command) is None and not os.path.isabs(login_command):
        task = _LoginTask(
            server_name=server_name, cookie_path=cookie_path,
            status="error", error=f"login_command not found: {login_command}",
        )
        _login_tasks[server_name] = task
        return task

    # 启动子进程 · cookie_path 通过 env 传给子进程(各 server 各自约定 env key ·
    # 本框架统一以 COOKIE_PATH 注入 · server 实现侧自行映射其期望的 env name)
    env = {**os.environ, "COOKIE_PATH": str(cookie_path)}
    cookie_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            login_command, *[str(a) for a in login_args],
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:  # noqa: BLE001
        task = _LoginTask(
            server_name=server_name, cookie_path=cookie_path,
            status="error", error=f"启动登录子进程失败: {exc}",
        )
        _login_tasks[server_name] = task
        return task

    import time as _time
    task = _LoginTask(
        server_name=server_name, cookie_path=cookie_path,
        proc=proc, status="running", started_at=_time.monotonic(),
    )
    _login_tasks[server_name] = task

    # background 等子进程结束 · 不阻塞 HTTP endpoint
    asyncio.create_task(
        _watch_login_proc(task), name=f"mcp-login-watch-{server_name}",
    )
    logger.info(
        "[mcp.browser_login] %s login subprocess started pid=%s cookie_path=%s",
        server_name, proc.pid, cookie_path,
    )
    return task


async def _watch_login_proc(task: _LoginTask) -> None:
    """background watcher · 子进程结束后判断 cookie 是否就位 · 更新 status。"""
    proc = task.proc
    if proc is None:
        return
    try:
        stderr_data = b""
        try:
            _, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=600,  # 10 min 扫码窗
            )
        except asyncio.TimeoutError:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            task.status = "error"
            task.error = "登录超时(10 分钟)· 请重新登录"
            return

        rc = proc.returncode
        if cookie_ready({"cookie_path": str(task.cookie_path)}):
            task.status = "cookie_ready"
            task.error = None
            logger.info(
                "[mcp.browser_login] %s login completed · cookie ready at %s",
                task.server_name, task.cookie_path,
            )
        else:
            task.status = "error"
            stderr_tail = stderr_data.decode("utf-8", errors="replace")[-400:]
            task.error = (
                f"登录子进程退出(rc={rc})但 cookie 未生成 · stderr: {stderr_tail}"
            )
            logger.warning(
                "[mcp.browser_login] %s login failed rc=%s · stderr=%r",
                task.server_name, rc, stderr_tail,
            )
    except Exception as exc:  # noqa: BLE001
        task.status = "error"
        task.error = f"watcher 异常: {exc}"
        logger.exception("[mcp.browser_login] %s watcher error", task.server_name)


def get_login_status(server_name: str, conf: dict) -> dict:
    """返 {status, error?, cookie_path, cookie_present}。

    status 三态:
        no_task          login 没启动 · 但 cookie_present 可能 True(历史登录留下)
        running          子进程在跑
        cookie_ready     刚登录完 · cookie 文件就位
        error            异常(error 字段含描述)
    """
    task = _login_tasks.get(server_name)
    cookie_path = _resolve_cookie_path(conf)
    cookie_present = cookie_ready(conf)
    if task is None:
        return {
            "status": "no_task",
            "cookie_path": str(cookie_path) if cookie_path else None,
            "cookie_present": cookie_present,
            "error": None,
        }
    return {
        "status": task.status,
        "cookie_path": str(task.cookie_path),
        "cookie_present": cookie_present,
        "error": task.error,
    }


def is_browser_login_entry(conf: dict) -> bool:
    """entry schema 标识为 browser_login? 用于 list_status 决定按钮是"配置凭证"
    还是"登录/重新登录"。"""
    return str(conf.get("auth") or "").strip().lower() == "browser_login"

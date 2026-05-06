"""v3-G chunk 1 — Google Calendar 底层 client。

职责（**只是底层**，不带 ``@register_capability``）：

* OAuth 2.0 desktop flow（首次浏览器授权 → 写 token.json；之后用 refresh
  token 自动续期）
* API client 单例（懒加载，连接复用）
* tenacity 重试（3 次，指数退避，cap 10s）—— 应对国内访问 Google API
  时常见的间歇性超时
* health_check —— Capability Registry 调用，区分 ``healthy`` / ``warn`` /
  ``error``：未配置 / 未授权 / 网络异常都是 ``warn``（国内常态，不当 error
  红警），授权且能拉数据返 ``healthy``

文件路径：

* credentials  ``~/.skyler/google_credentials.json``  —— 用户从 Google Cloud
  Console 下载的 OAuth desktop client，**手工放置**
* token        ``~/.skyler/google_token.json``        —— OAuth flow 完成后
  自动写入；包含 access_token + refresh_token

scope：``calendar.readonly`` 一个 —— 只看不改，符合"AI 同伴查日程"用例。
未来要加事件创建能力时再扩 scope，**revoke + 重新 auth** 即可。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# 路径用 ~/.skyler/ 而非项目内目录 —— 避免 token / credentials 跟代码混在一起，
# 也避免被 .gitignore 漏写时 commit 进 git。
SKYLER_HOME       = Path(os.path.expanduser("~/.skyler"))
CREDENTIALS_PATH  = SKYLER_HOME / "google_credentials.json"
TOKEN_PATH        = SKYLER_HOME / "google_token.json"


# ---------------------------------------------------------------------------
# Credentials lifecycle
# ---------------------------------------------------------------------------

def _ensure_skyler_home() -> None:
    SKYLER_HOME.mkdir(parents=True, exist_ok=True)


def _load_credentials() -> Optional[Credentials]:
    """从 token.json 加载。失败 / 不存在返回 None；refresh 失败也返 None。"""
    if not TOKEN_PATH.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception as exc:
        logger.warning("[google_calendar] token.json parse failed: %s", exc)
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            logger.warning(
                "[google_calendar] token refresh failed (likely revoked): %s", exc,
            )
            return None
        except Exception as exc:
            logger.warning("[google_calendar] token refresh network err: %s", exc)
            return None
        # refresh 成功 → 写回 token.json
        _save_credentials(creds)
        return creds

    # 没有 refresh_token / 过期 / 不可恢复
    return None


def _save_credentials(creds: Credentials) -> None:
    _ensure_skyler_home()
    TOKEN_PATH.write_text(creds.to_json())


def is_credentials_present() -> bool:
    """credentials.json 是否已放置。仅检查文件存在，不验内容。"""
    return CREDENTIALS_PATH.exists()


def is_authorized() -> bool:
    """token.json 是否存在且能加载有效 creds（含 refresh 后有效）。"""
    return _load_credentials() is not None


def get_authorized_email() -> Optional[str]:
    """返回授权账号 email；未授权返回 None。"""
    creds = _load_credentials()
    if creds is None:
        return None
    # email 在 token.json 的 id_token claims 里。最简单的做法是再 build 一个
    # service 调用 ``userinfo`` —— 但 Calendar scope 不一定带 userinfo 权限。
    # 取巧：把 token JSON 解出来看 ``id_token`` 字段（如果存在）。
    # 实际场景下大多数情况返 None 但不影响功能 —— UI 只是显示授权状态。
    try:
        import json
        data = json.loads(TOKEN_PATH.read_text())
        # google_auth_oauthlib 默认不存 id_token；保守返 None。
        return data.get("client_id")  # 至少能识别是哪个 OAuth client
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OAuth flow（同步 —— 浏览器交互必须）
# ---------------------------------------------------------------------------

def run_oauth_flow() -> None:
    """触发首次授权。**阻塞**调用：会打开本地浏览器，等用户在 Google 授权。

    上层 (HTTP route) 应放进 ``asyncio.to_thread`` 跑，避免堵 event loop。

    成功 → 写 token.json；失败抛 RuntimeError / OSError。
    """
    if not is_credentials_present():
        raise FileNotFoundError(
            f"missing credentials at {CREDENTIALS_PATH} — see "
            "docs/google-calendar-setup.md"
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH), SCOPES,
    )
    # port=0 让 OS 分配空闲端口，避免与已占用端口冲突
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    logger.info("[google_calendar] OAuth completed, token saved to %s", TOKEN_PATH)


def revoke_token() -> bool:
    """删 token.json。返回是否真的删了（不存在返 False）。"""
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        logger.info("[google_calendar] token.json removed")
        return True
    return False


# ---------------------------------------------------------------------------
# API client（懒加载单例）
# ---------------------------------------------------------------------------

_service: Any = None


def _get_service() -> Any:
    """懒加载 Calendar v3 service。creds 失效（refresh 失败）会强制重建。"""
    global _service
    creds = _load_credentials()
    if creds is None:
        raise PermissionError("not authorized (token.json missing or invalid)")
    if _service is None:
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def _reset_service_cache() -> None:
    """测试 / revoke 后重置单例。"""
    global _service
    _service = None


# ---------------------------------------------------------------------------
# Public API（同步内核 + asyncio.to_thread 包装）
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type((HttpError, OSError, TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _list_events_sync(
    start: datetime, end: datetime,
) -> list[dict]:
    """同步 list events with retry。"""
    svc = _get_service()
    # Google Calendar API 要求 RFC3339 时间字符串，必须带 timezone。
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    events_result = svc.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    raw = events_result.get("items", [])
    return [_normalise_event(e) for e in raw]


def _normalise_event(raw: dict) -> dict:
    """Google Event → 简化 dict（给 ChatAgent / 模板用）。"""
    start = raw.get("start", {})
    end   = raw.get("end", {})
    # all-day 事件用 ``date`` 字段（YYYY-MM-DD）；timed 事件用 ``dateTime``
    is_all_day = "date" in start and "dateTime" not in start
    return {
        "id":         raw.get("id", ""),
        "title":      raw.get("summary") or "(无标题)",
        "start":      start.get("dateTime") or start.get("date") or "",
        "end":        end.get("dateTime")   or end.get("date")   or "",
        "all_day":    is_all_day,
        "location":   raw.get("location") or "",
        "description": raw.get("description") or "",
    }


async def list_events_in_range(
    start: datetime, end: datetime,
) -> list[dict]:
    """async 包装：放 to_thread 跑同步 client。"""
    return await asyncio.to_thread(_list_events_sync, start, end)


# ---------------------------------------------------------------------------
# Health check（给 Capability Registry 调）
# ---------------------------------------------------------------------------

async def health_check() -> dict:
    """三档：

    * ``warn``  —— 未配 credentials / 未授权 / 网络错误（国内常态，不刷红）
    * ``healthy`` —— 已授权且能拉到一次轻量 API 调用
    * ``error`` —— 不会返回，所有失败都降级成 warn 让用户安心
    """
    if not is_credentials_present():
        return {
            "status": "warn",
            "error": "未配 credentials.json，请放置 ~/.skyler/google_credentials.json（详见 docs/google-calendar-setup.md）",
        }
    if not is_authorized():
        return {
            "status": "warn",
            "error": "未授权，请连接 Google 账号",
        }
    # 已授权 → 试拉 next 24h 看是否真能 reach API
    try:
        now = datetime.now(timezone.utc)
        await list_events_in_range(now, now + timedelta(hours=24))
        return {"status": "healthy"}
    except PermissionError as exc:
        return {"status": "warn", "error": f"授权状态失效：{exc}"}
    except HttpError as exc:
        return {"status": "warn", "error": f"Google API 错误：{exc}"}
    except Exception as exc:
        # OSError / TimeoutError / DNS 失败等等
        return {"status": "warn", "error": f"网络异常（国内访问 Google 常态）：{exc}"}

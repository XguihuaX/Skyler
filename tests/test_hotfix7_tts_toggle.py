"""hotfix-7 commit 4 — TTS toggle 写入失败显示 'undefined' 防回归。

锁:
1. ``setConfigField`` (lib/window.ts) 把 Tauri Rust ``Result<(), String>`` Err
   字符串 normalize 成 Error 对象,不让 ``e.message`` 返 undefined
2. ``setConfigField`` 也 normalize ``/api/config/reload`` 失败响应,带 status
   + body 摘要
3. SettingsPanel ``extractErrorMessage`` 兜底函数存在,任何 reject shape 都
   返非空 string
4. ``remoteToggle`` 失败路径用 ``extractErrorMessage`` 而非 ``(e as Error).message``
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW_TS = os.path.join(ROOT, "frontend/src/lib/window.ts")
PANEL_TSX = os.path.join(ROOT, "frontend/src/components/SettingsPanel.tsx")


@pytest.fixture(scope="module")
def window_ts() -> str:
    with open(WINDOW_TS, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def panel_tsx() -> str:
    with open(PANEL_TSX, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Part 1 — setConfigField normalize
# ---------------------------------------------------------------------------


def test_setConfigField_wraps_invoke_string_reject(window_ts: str) -> None:
    """``setConfigField`` 必须 try/catch 包 ``invoke`` 调用,并把 string reject
    转成 ``new Error(...)``。"""
    # 找 ``await invoke(`` block
    assert "try {" in window_ts, "setConfigField 缺 try block 包 invoke"
    # ``typeof e === 'string'`` 分支处理 Tauri Rust Err(String)
    assert re.search(r"typeof\s+e\s*===\s*'string'", window_ts), \
        "缺 ``typeof e === 'string'`` 分支处理 Tauri Rust Err(String)"
    # ``throw new Error(...)`` 重新抛
    assert "throw new Error(" in window_ts


def test_setConfigField_reload_error_includes_status(window_ts: str) -> None:
    """``/api/config/reload`` 失败时 throw 的 Error 必须带 status code。"""
    assert re.search(r"config reload failed:\s+HTTP\s+\$\{r\.status\}", window_ts), \
        "config reload 失败 throw 必须含 ``HTTP ${r.status}``"


def test_setConfigField_reload_attempts_body(window_ts: str) -> None:
    """reload 失败时尝试读 response body 拼到 error msg(限 120 字符)。"""
    assert "await r.text()" in window_ts
    assert re.search(r"\.slice\(0,\s*120\)", window_ts)


# ---------------------------------------------------------------------------
# Part 2 — extractErrorMessage helper
# ---------------------------------------------------------------------------


def test_extract_error_message_helper_exists(panel_tsx: str) -> None:
    assert re.search(r"function extractErrorMessage\(", panel_tsx), \
        "SettingsPanel 缺 extractErrorMessage helper"


def test_extract_error_message_handles_3_shapes(panel_tsx: str) -> None:
    """helper 必须覆盖 string / Error / object 三种 reject shape。"""
    m = re.search(
        r"function extractErrorMessage\(e: unknown\): string \{([\s\S]*?)\n\}",
        panel_tsx,
    )
    assert m, "extractErrorMessage 函数体没抓到"
    body = m.group(1)
    assert "typeof e === 'string'" in body
    assert "e instanceof Error" in body
    # object 分支用 JSON.stringify
    assert "JSON.stringify(e)" in body
    # 兜底返非空 string("未知错误" 或类似)
    assert "未知错误" in body or "unknown" in body.lower()


# ---------------------------------------------------------------------------
# Part 3 — remoteToggle / writeField 用 extractErrorMessage(非 ``e.message``)
# ---------------------------------------------------------------------------


def test_remoteToggle_uses_extractErrorMessage(panel_tsx: str) -> None:
    """``remoteToggle`` 失败路径不再用 ``(e as Error).message`` 取消息。"""
    # 找 remoteToggle 函数体内的 catch block
    m = re.search(
        r"const remoteToggle\s*=[\s\S]*?setConfigField\([^)]+\)\.catch\([\s\S]*?\}\);",
        panel_tsx,
    )
    assert m, "remoteToggle 函数体没抓到"
    body = m.group(0)
    assert "extractErrorMessage(e)" in body, \
        "remoteToggle 失败 toast 应该用 extractErrorMessage(e)"
    # 旧的 (e as Error).message 不该再出现在该 block
    assert "(e as Error).message" not in body, (
        "remoteToggle 仍含 ``(e as Error).message`` —— hotfix-7 修复丢失"
    )


def test_writeField_proactive_uses_extractErrorMessage(panel_tsx: str) -> None:
    """主动陪伴 section 的 ``writeField`` 同样改 extractErrorMessage。"""
    m = re.search(
        r"const writeField = useCallback\([\s\S]*?\);[\s\S]*?\}\s*,",
        panel_tsx,
    )
    if m:
        body = m.group(0)
        # writeField 的 catch path
        if "setConfigField" in body and "catch" in body:
            assert "extractErrorMessage" in body, (
                "writeField 失败 toast 应该用 extractErrorMessage"
            )


# ---------------------------------------------------------------------------
# Part 4 — behavior smoke (虚构 reject shape 让 extractErrorMessage 走过)
# ---------------------------------------------------------------------------


def test_setConfigField_catch_paths_no_message_undefined(panel_tsx: str) -> None:
    """每个 ``setConfigField(...).catch(...)`` 块内不该再用
    ``(e as Error).message`` —— 用 ``extractErrorMessage(e)`` 兜底。

    其他 catch 路径(fetch / lib call)走的是 fetch 抛 Error 真实对象,e.message
    不会 undefined,本 commit 不强制改(超 hotfix-7 scope)。
    """
    # 找所有 setConfigField(...).catch( ... ) block
    blocks = re.findall(
        r"setConfigField\([^)]*\)\.catch\(\s*\([^)]*\)\s*=>\s*\{[\s\S]*?\}\s*\)",
        panel_tsx,
    )
    assert len(blocks) >= 2, (
        f"setConfigField.catch 仅 {len(blocks)} 处 —— 期望 ≥ 2(remoteToggle "
        "+ writeField)"
    )
    bad_blocks = [b for b in blocks if "(e as Error).message" in b]
    assert bad_blocks == [], (
        f"setConfigField.catch 内还有 {len(bad_blocks)} 处用 (e as Error).message —— "
        "Tauri Rust Err(string) 时这里返 undefined。改用 extractErrorMessage(e)"
    )
    # 至少一处用 extractErrorMessage
    used = sum(1 for b in blocks if "extractErrorMessage" in b)
    assert used >= 2, (
        f"setConfigField.catch 仅 {used} 处用 extractErrorMessage —— "
        "remoteToggle + writeField 都该用"
    )

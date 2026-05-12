"""v3.5 chunk 8a commit 1 — activity_monitor 单元测试。

不调真 macOS API。Mock NSWorkspace 单例 + ``subprocess.run`` 让 AppleScript
返预设输出，跑完整解析路径。非 macOS 平台分支也覆盖。
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import activity_monitor as am


# ---------------------------------------------------------------------------
# get_active_app
# ---------------------------------------------------------------------------


def test_get_active_app_returns_localized_name() -> None:
    fake_app = MagicMock()
    fake_app.localizedName.return_value = "Visual Studio Code"
    fake_ws = MagicMock()
    fake_ws.frontmostApplication.return_value = fake_app
    fake_NSWorkspace = MagicMock()
    fake_NSWorkspace.sharedWorkspace.return_value = fake_ws
    with patch.object(am, "_NSWorkspace", fake_NSWorkspace), \
         patch.object(am, "IS_MACOS", True):
        assert am.get_active_app() == "Visual Studio Code"


def test_get_active_app_none_when_no_frontmost() -> None:
    fake_ws = MagicMock()
    fake_ws.frontmostApplication.return_value = None
    fake_NSWorkspace = MagicMock()
    fake_NSWorkspace.sharedWorkspace.return_value = fake_ws
    with patch.object(am, "_NSWorkspace", fake_NSWorkspace), \
         patch.object(am, "IS_MACOS", True):
        assert am.get_active_app() is None


def test_get_active_app_none_on_non_macos() -> None:
    with patch.object(am, "IS_MACOS", False):
        assert am.get_active_app() is None


def test_get_active_app_none_when_pyobjc_missing() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch.object(am, "_NSWorkspace", None):
        assert am.get_active_app() is None


# ---------------------------------------------------------------------------
# _parse_url_title
# ---------------------------------------------------------------------------


def test_parse_url_title_record_separator() -> None:
    raw = "https://example.com/pageExample Title"
    assert am._parse_url_title(raw) == ("https://example.com/page", "Example Title")


def test_parse_url_title_tab_fallback() -> None:
    raw = "https://example.com\tHello"
    assert am._parse_url_title(raw) == ("https://example.com", "Hello")


def test_parse_url_title_url_only() -> None:
    assert am._parse_url_title("https://example.com") == ("https://example.com", "")


def test_parse_url_title_none_or_empty() -> None:
    assert am._parse_url_title(None) is None
    assert am._parse_url_title("") is None
    assert am._parse_url_title("   ") is None


# ---------------------------------------------------------------------------
# Browser tabs (mock _run_osascript)
# ---------------------------------------------------------------------------


def test_get_chrome_active_tab_parses_record_separator() -> None:
    with patch.object(am, "_run_osascript",
                      return_value="https://github.com/skylerskyler/skyler"):
        assert am.get_chrome_active_tab() == ("https://github.com/skyler", "skyler/skyler")


def test_get_chrome_active_tab_empty_when_no_window() -> None:
    with patch.object(am, "_run_osascript", return_value=""):
        assert am.get_chrome_active_tab() is None


def test_get_chrome_active_tab_none_on_osascript_failure() -> None:
    with patch.object(am, "_run_osascript", return_value=None):
        assert am.get_chrome_active_tab() is None


def test_get_safari_active_tab() -> None:
    with patch.object(am, "_run_osascript",
                      return_value="https://apple.comApple"):
        assert am.get_safari_active_tab() == ("https://apple.com", "Apple")


# ---------------------------------------------------------------------------
# _run_osascript (mock subprocess)
# ---------------------------------------------------------------------------


def test_run_osascript_none_non_macos() -> None:
    with patch.object(am, "IS_MACOS", False):
        assert am._run_osascript('return "x"') is None


def test_run_osascript_returns_stdout() -> None:
    fake_completed = MagicMock(returncode=0, stdout="hello world\n", stderr="")
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run", return_value=fake_completed):
        assert am._run_osascript('say x') == "hello world"


def test_run_osascript_returncode_nonzero_returns_none() -> None:
    fake_completed = MagicMock(returncode=1, stdout="", stderr="Not authorized")
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run", return_value=fake_completed):
        assert am._run_osascript("...") is None


def test_run_osascript_timeout_returns_none() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=2.0)):
        assert am._run_osascript("...") is None


# ---------------------------------------------------------------------------
# get_active_document_path
# ---------------------------------------------------------------------------


def test_get_active_document_word() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch.object(am, "get_active_app", return_value="Microsoft Word"), \
         patch.object(am, "_run_osascript", return_value="/Users/me/Doc.docx"):
        assert am.get_active_document_path() == ("/Users/me/Doc.docx", "word")


def test_get_active_document_pages_fallback() -> None:
    """active_app=Pages → Pages 被提到队首先问，命中即返。"""
    with patch.object(am, "IS_MACOS", True), \
         patch.object(am, "get_active_app", return_value="Pages"), \
         patch.object(am, "_run_osascript", return_value="/Users/me/draft.pages"):
        result = am.get_active_document_path()
    assert result == ("/Users/me/draft.pages", "pages")


def test_get_active_document_word_first_in_default_order() -> None:
    """active_app 不是 Word/Pages（比如 Chrome）→ 按 _DOC_APPS 默认顺序 Word 在前。"""
    call_args: list[str] = []

    def fake_run(script: str) -> str:
        call_args.append(script)
        # 第一次（Word）返路径
        if len(call_args) == 1:
            return "/Users/me/doc.docx"
        return ""

    with patch.object(am, "IS_MACOS", True), \
         patch.object(am, "get_active_app", return_value="Chrome"), \
         patch.object(am, "_run_osascript", side_effect=fake_run):
        result = am.get_active_document_path()
    assert result == ("/Users/me/doc.docx", "word")
    # 只问了 Word，Pages 没 fall through
    assert len(call_args) == 1


def test_get_active_document_none_when_no_doc_apps() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch.object(am, "get_active_app", return_value="Chrome"), \
         patch.object(am, "_run_osascript", return_value=""):
        assert am.get_active_document_path() is None


def test_get_active_document_none_non_macos() -> None:
    with patch.object(am, "IS_MACOS", False):
        assert am.get_active_document_path() is None

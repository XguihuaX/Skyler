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


def _mock_osascript_run(stdout: str = "", returncode: int = 0,
                         stderr: str = ""):
    """构造 osascript subprocess.run 的 fake CompletedProcess。"""
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def test_get_active_app_returns_bundle_name() -> None:
    """[hotfix-10] osascript ``POSIX path of ...`` →
    ``/Applications/Safari.app/`` → basename → bundle name ``Safari``。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run",
                      return_value=_mock_osascript_run("/Applications/Safari.app/\n")):
        assert am.get_active_app() == "Safari"


def test_get_active_app_vscode_bundle_name() -> None:
    """[hotfix-10] VSCode CFBundleName is ``Code``,而非 ``Visual Studio Code``。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run", return_value=_mock_osascript_run(
             "/Applications/Visual Studio Code.app/Contents/MacOS/../../../"
             "Visual Studio Code.app/\n",
         )):
        # osascript 实测返 ``/Applications/Visual Studio Code.app/`` —— basename
        # 取 ``Visual Studio Code``。bundle 名是否 == CFBundleName 看 .app 目录
        # 名 vs Info.plist。这里测目录名(实际 macOS 返这个)。
        # 不论是 ``Code.app`` 还是 ``Visual Studio Code.app``,我们直接信 basename。
        got = am.get_active_app()
        # 真机案例 ``Visual Studio Code.app`` 目录 → ``"Visual Studio Code"``
        assert got == "Visual Studio Code"


def test_get_active_app_terminal_returns_english() -> None:
    """[hotfix-10] 中文 macOS NSWorkspace.localizedName 返 ``"终端"``,但 osascript
    POSIX path 永远返英文 bundle 目录名 ``Terminal``。这是 hotfix-10 核心收益。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run", return_value=_mock_osascript_run(
             "/System/Applications/Utilities/Terminal.app/\n",
         )):
        assert am.get_active_app() == "Terminal"


def test_get_active_app_strips_trailing_slash_and_app() -> None:
    """``/Path/Foo.app/`` → ``Foo``;``/Path/Foo.app`` (无尾 slash)同样工作。"""
    for raw, want in [
        ("/Applications/Slack.app/\n", "Slack"),
        ("/Applications/Slack.app\n", "Slack"),
        ("/Applications/Slack.app/", "Slack"),
        # 极端:bundle 不带 ``.app`` 后缀(理论上 osascript 总有 .app,但 robust)
        ("/Applications/RawBundle/", "RawBundle"),
    ]:
        with patch.object(am, "IS_MACOS", True), \
             patch("backend.integrations.activity_monitor.shutil.which",
                   return_value="/usr/bin/osascript"), \
             patch.object(am.subprocess, "run",
                          return_value=_mock_osascript_run(raw)):
            assert am.get_active_app() == want


def test_get_active_app_none_on_non_macos() -> None:
    with patch.object(am, "IS_MACOS", False):
        assert am.get_active_app() is None


def test_get_active_app_none_when_osascript_missing() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value=None):
        assert am.get_active_app() is None


def test_get_active_app_none_on_osascript_failure() -> None:
    """非零 returncode → silent None(用户未授权 / 极端情况)。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run",
                      return_value=_mock_osascript_run(
                          returncode=1, stderr="Not authorized")):
        assert am.get_active_app() is None


def test_get_active_app_none_on_timeout() -> None:
    """osascript hang > 2s → TimeoutExpired → silent None。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired(
                          cmd="osascript", timeout=2.0)):
        assert am.get_active_app() is None


def test_get_active_app_none_on_empty_stdout() -> None:
    """osascript exit 0 但 stdout 空(极端 race 条件)→ None。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/bin/osascript"), \
         patch.object(am.subprocess, "run",
                      return_value=_mock_osascript_run("   \n")):
        assert am.get_active_app() is None


# ---------------------------------------------------------------------------
# v3.5 hotfix-10 — get_display_name (LLM-facing app name 本地化)
# ---------------------------------------------------------------------------


def test_get_display_name_maps_known_bundles() -> None:
    assert am.get_display_name("Code") == "VS Code"
    assert am.get_display_name("Code - Insiders") == "VS Code Insiders"
    assert am.get_display_name("Terminal") == "终端"


def test_get_display_name_passthrough_unknown_bundles() -> None:
    """未列入 mapping 表 → 直接返原值(国际化品牌名英文 OK)。"""
    assert am.get_display_name("Safari") == "Safari"
    assert am.get_display_name("Spotify") == "Spotify"
    assert am.get_display_name("Slack") == "Slack"
    assert am.get_display_name("Notion") == "Notion"


def test_get_display_name_handles_none_and_empty() -> None:
    """None / 空串 → ``"(unknown)"`` 兜底(防 None 串到 LLM prompt)。"""
    assert am.get_display_name(None) == "(unknown)"
    assert am.get_display_name("") == "(unknown)"


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
# v3.5 hotfix-9 — get_browser_url (frontmost-gated)
# ---------------------------------------------------------------------------


def test_get_browser_url_chrome_frontmost_returns_tab() -> None:
    """Chrome 是 frontmost → 路由到 chrome AppleScript,返三元组。"""
    with patch.object(am, "get_active_app", return_value="Google Chrome"), \
         patch.object(am, "get_chrome_active_tab",
                      return_value=("https://bilibili.com/jobs", "招聘")):
        assert am.get_browser_url() == ("chrome", "https://bilibili.com/jobs", "招聘")


def test_get_browser_url_safari_frontmost_returns_tab() -> None:
    with patch.object(am, "get_active_app", return_value="Safari"), \
         patch.object(am, "get_safari_active_tab",
                      return_value=("https://apple.com", "Apple")):
        assert am.get_browser_url() == ("safari", "https://apple.com", "Apple")


def test_get_browser_url_non_browser_frontmost_returns_none() -> None:
    """**hotfix-9 核心 case**: frontmost 是 IDE / 自家 app → 不报浏览器 URL,
    即使 Chrome 后台还开着 bilibili tab。chrome AppleScript 都不会被调。"""
    chrome_mock = MagicMock()
    with patch.object(am, "get_active_app", return_value="Visual Studio Code"), \
         patch.object(am, "get_chrome_active_tab", chrome_mock):
        assert am.get_browser_url() is None
    chrome_mock.assert_not_called()


def test_get_browser_url_momoos_frontmost_returns_none() -> None:
    """用户切到 Skyler 自家窗口 → 不报后台 Chrome 的 URL。"""
    with patch.object(am, "get_active_app", return_value="momoos"), \
         patch.object(am, "get_chrome_active_tab",
                      return_value=("https://leaked.example", "leaked")), \
         patch.object(am, "get_safari_active_tab",
                      return_value=("https://also-leaked.example", "x")):
        assert am.get_browser_url() is None


def test_get_browser_url_chinese_terminal_frontmost_returns_none() -> None:
    """hotfix-8 i18n 教训:中文 macOS frontmost 可能返"终端"(Apple 原生),
    确认非浏览器路径 graceful。"""
    with patch.object(am, "get_active_app", return_value="终端"):
        assert am.get_browser_url() is None


def test_get_browser_url_active_app_none_returns_none() -> None:
    """get_active_app 自身失败 → 短路 None。"""
    with patch.object(am, "get_active_app", return_value=None):
        assert am.get_browser_url() is None


def test_get_browser_url_chrome_frontmost_but_no_window_returns_none() -> None:
    """Chrome 是 frontmost 但 AppleScript 返 None(没 window / 未授权)→ None。"""
    with patch.object(am, "get_active_app", return_value="Google Chrome"), \
         patch.object(am, "get_chrome_active_tab", return_value=None):
        assert am.get_browser_url() is None


def test_get_browser_url_recognized_but_unimplemented_browser_returns_none() -> None:
    """Firefox / Edge / Arc 等在 _BROWSER_APPS 但无 AppleScript impl → None。

    用户在 Firefox 时与 hotfix-9 前行为一致(走 app:Firefox stay,不报 URL)。
    """
    chrome_mock = MagicMock()
    safari_mock = MagicMock()
    with patch.object(am, "get_active_app", return_value="Firefox"), \
         patch.object(am, "get_chrome_active_tab", chrome_mock), \
         patch.object(am, "get_safari_active_tab", safari_mock):
        assert am.get_browser_url() is None
    chrome_mock.assert_not_called()
    safari_mock.assert_not_called()


def test_get_browser_url_case_insensitive_match() -> None:
    """frontmost localizedName 大小写 / 前后空格 → 正则化命中。"""
    with patch.object(am, "get_active_app", return_value="  google chrome  "), \
         patch.object(am, "get_chrome_active_tab",
                      return_value=("https://x.com", "X")):
        assert am.get_browser_url() == ("chrome", "https://x.com", "X")


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

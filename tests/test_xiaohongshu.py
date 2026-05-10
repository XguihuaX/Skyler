"""v3.5 chunk 6c — xiaohongshu integration + capability 测试。

不打真实小红书（网络依赖 + anti-bot 不稳）；用 httpx Mock 替换 client。
HTML fixtures 模拟 __INITIAL_STATE__ / og:meta / 反爬 412 / parse_failed
各场景。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import xiaohongshu as xhs
from backend.capabilities import xiaohongshu as xhs_cap
from backend.capabilities import CapabilityRegistry
from backend.tools.registry import ToolRegistry

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. URL validation
# ---------------------------------------------------------------------------

def test_url_validation():
    print("\n[_is_allowed_url — 域名白名单]")
    check("xiaohongshu.com OK",
          xhs._is_allowed_url("https://www.xiaohongshu.com/explore/abc123"))
    check("xhslink.com OK",
          xhs._is_allowed_url("https://xhslink.com/abcd"))
    check("subdomain OK",
          xhs._is_allowed_url("https://m.xiaohongshu.com/explore/abc"))
    check("evil.com containing xiaohongshu reject",
          not xhs._is_allowed_url("https://evil.com/xiaohongshu.com/x"))
    check("empty reject", not xhs._is_allowed_url(""))
    check("non-string reject",
          not xhs._is_allowed_url(None))  # type: ignore
    check("non-http reject",
          not xhs._is_allowed_url("ftp://xiaohongshu.com/"))


# ---------------------------------------------------------------------------
# 2. __INITIAL_STATE__ JSON parsing
# ---------------------------------------------------------------------------

def test_parse_initial_state_basic():
    print("\n[_parse_initial_state — 基本 JSON 解析]")
    raw = '{"a": 1, "b": "hello"}'
    out = xhs._parse_initial_state(raw)
    check("parsed dict", out == {"a": 1, "b": "hello"})


def test_parse_initial_state_undefined():
    print("\n[_parse_initial_state — undefined → null]")
    raw = '{"a": undefined, "b": "x"}'
    out = xhs._parse_initial_state(raw)
    check("undefined → null", out == {"a": None, "b": "x"})


def test_parse_initial_state_truncated():
    print("\n[_parse_initial_state — trailing 字符 fallback 截到最后 }]")
    raw = '{"a": 1}garbage'
    out = xhs._parse_initial_state(raw)
    check("truncated parse ok", out == {"a": 1})


def test_parse_initial_state_invalid():
    print("\n[_parse_initial_state — 完全 garbled 返 None]")
    out = xhs._parse_initial_state("not json at all")
    check("returns None", out is None)


# ---------------------------------------------------------------------------
# 3. _extract_note_from_initial_state
# ---------------------------------------------------------------------------

def test_extract_note_path_noteDetailMap():
    print("\n[_extract_note_from_initial_state — noteDetailMap path]")
    state = {"note": {"noteDetailMap": {"abc123": {"note": {
        "title": "笔记标题", "desc": "正文", "imageList": [
            {"urlDefault": "https://img1.jpg"},
        ]}}}}}
    note = xhs._extract_note_from_initial_state(state)
    check("found note", note is not None)
    check("title preserved", note.get("title") == "笔记标题")


def test_extract_note_path_note_note():
    print("\n[_extract_note_from_initial_state — note.note path]")
    state = {"note": {"note": {"title": "X", "desc": "y"}}}
    note = xhs._extract_note_from_initial_state(state)
    check("found", note is not None and note.get("title") == "X")


def test_extract_note_path_noteData():
    print("\n[_extract_note_from_initial_state — noteData.data.noteInfo path]")
    state = {"noteData": {"data": {"noteInfo": {
        "title": "Z", "desc": "w", "imageList": [],
    }}}}
    note = xhs._extract_note_from_initial_state(state)
    check("found", note is not None and note.get("title") == "Z")


def test_extract_note_not_found():
    print("\n[_extract_note_from_initial_state — 无匹配返 None]")
    state = {"unrelated": {"foo": "bar"}}
    note = xhs._extract_note_from_initial_state(state)
    check("returns None", note is None)


# ---------------------------------------------------------------------------
# 4. og:meta extraction
# ---------------------------------------------------------------------------

def test_extract_og_meta():
    print("\n[_extract_og_meta — 多 og: tag 提取]")
    html = (
        '<meta property="og:title" content="测试标题">'
        '<meta property="og:description" content="一段描述">'
        '<meta property="og:image" content="https://img.jpg">'
        '<meta property="og:url" content="https://x.com/n/123">'
    )
    out = xhs._extract_og_meta(html)
    check("title", out.get("title") == "测试标题")
    check("description", out.get("description") == "一段描述")
    check("image", out.get("image") == "https://img.jpg")


def test_extract_og_meta_twitter_fallback():
    print("\n[_extract_og_meta — twitter:image 兜底]")
    html = (
        '<meta property="og:title" content="t">'
        '<meta name="twitter:image" content="https://twit.jpg">'
    )
    out = xhs._extract_og_meta(html)
    check("twitter:image used as image",
          out.get("image") == "https://twit.jpg")


# ---------------------------------------------------------------------------
# 5. parse_post end-to-end (mocked httpx)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status: int, text: str, url: str = ""):
        self.status_code = status
        self.text = text
        self.url = url or "https://www.xiaohongshu.com/explore/fake"


async def _mock_client_returning(resp: _FakeResp):
    """Async context manager returning a mock AsyncClient that returns ``resp``."""
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=resp)
    return fake_client


async def test_parse_post_invalid_url():
    print("\n[parse_post — 域名外拒]")
    r = await xhs.parse_post("https://evil.com/x")
    check("invalid_url", r.get("error") == "invalid_url")


async def test_parse_post_initial_state_path():
    print("\n[parse_post — __INITIAL_STATE__ happy path]")
    # 5 个 object {，需要 5 个 }；arrays 单独平衡
    html = (
        '<html>...<script>'
        'window.__INITIAL_STATE__ = {"note":{"noteDetailMap":{"abc":'
        '{"note":{"title":"测试标题","desc":"一段笔记内容",'
        '"imageList":[{"urlDefault":"https://img.jpg"}],'
        '"user":{"nickname":"作者A"},"tagList":[{"name":"美食"}]}}}}}'
        '</script>...</html>'
    )
    fake_client = await _mock_client_returning(_FakeResp(200, html))
    with patch("backend.integrations.xiaohongshu.httpx.AsyncClient",
               return_value=fake_client):
        r = await xhs.parse_post("https://www.xiaohongshu.com/explore/abc")
        check("source initial_state", r.get("source") == "initial_state")
        check("title", r.get("title") == "测试标题")
        check("text", r.get("text") == "一段笔记内容")
        check("images count 1", len(r.get("images") or []) == 1)
        check("author", r.get("author") == "作者A")
        check("tags", r.get("tags") == ["美食"])


async def test_parse_post_og_fallback():
    print("\n[parse_post — 无 __INITIAL_STATE__，og fallback]")
    html = (
        '<html><head>'
        '<meta property="og:title" content="OG 标题">'
        '<meta property="og:description" content="OG 描述">'
        '<meta property="og:image" content="https://og.jpg">'
        '</head></html>'
    )
    fake_client = await _mock_client_returning(_FakeResp(200, html))
    with patch("backend.integrations.xiaohongshu.httpx.AsyncClient",
               return_value=fake_client):
        r = await xhs.parse_post("https://www.xiaohongshu.com/explore/x")
        check("source og_meta", r.get("source") == "og_meta")
        check("title from og", r.get("title") == "OG 标题")
        check("text from og description", r.get("text") == "OG 描述")
        check("image present", r.get("images") == ["https://og.jpg"])


async def test_parse_post_blocked():
    print("\n[parse_post — 412 反爬]")
    fake_client = await _mock_client_returning(_FakeResp(412, ""))
    with patch("backend.integrations.xiaohongshu.httpx.AsyncClient",
               return_value=fake_client):
        r = await xhs.parse_post("https://www.xiaohongshu.com/explore/x")
        check("blocked_by_antibot", r.get("error") == "blocked_by_antibot")
        check("status echoed", r.get("status") == 412)
        check("hint mentions 反爬", "反爬限流" in (r.get("hint") or ""))


async def test_parse_post_parse_failed():
    print("\n[parse_post — 200 但无可解析元数据]")
    fake_client = await _mock_client_returning(_FakeResp(
        200, "<html><body>empty</body></html>"))
    with patch("backend.integrations.xiaohongshu.httpx.AsyncClient",
               return_value=fake_client):
        r = await xhs.parse_post("https://www.xiaohongshu.com/explore/x")
        check("parse_failed", r.get("error") == "parse_failed")


async def test_parse_post_non_200_other():
    print("\n[parse_post — 500 其他 http error]")
    fake_client = await _mock_client_returning(_FakeResp(500, ""))
    with patch("backend.integrations.xiaohongshu.httpx.AsyncClient",
               return_value=fake_client):
        r = await xhs.parse_post("https://www.xiaohongshu.com/explore/x")
        check("http_error", r.get("error") == "http_error")
        check("status 500", r.get("status") == 500)


# ---------------------------------------------------------------------------
# 6. Capability registration + red-line message
# ---------------------------------------------------------------------------

def test_only_one_xhs_capability():
    print("\n[xhs capability — 只暴露 1 个 parse_url（无主动爬接口）]")
    reg = CapabilityRegistry()
    xhs_caps = [c.name for c in reg.list_all() if c.name.startswith("xhs.")]
    check("exactly 1 xhs cap", len(xhs_caps) == 1, f"got {xhs_caps}")
    check("name is parse_url", xhs_caps == ["xhs.parse_url"])
    # 模块没有 search / recommend / fetch_homepage 等方法
    forbidden = ["search", "recommend", "fetch_homepage", "list_followings"]
    for f in forbidden:
        check(f"integrations.xhs no `{f}` method",
              not hasattr(xhs, f),
              f"unexpected method exposed")


def test_description_redlines():
    print("\n[xhs.parse_url description — 红线明文]")
    reg = CapabilityRegistry()
    cap = next((c for c in reg.list_all() if c.name == "xhs.parse_url"), None)
    check("cap found", cap is not None)
    if cap:
        d = cap.description or ""
        check("'只做被动' verbatim", "只做被动" in d)
        check("'不要瞎编' verbatim", "不要瞎编" in d)
        check("'没有' main capability hint", "没有" in d)


def test_addendum_redlines():
    print("\n[system prompt — 【小红书 URL 解析】verbatim]")
    from backend.agents.chat import _TOOL_PROMPT_ADDENDUM
    check("contains 【小红书 URL 解析】",
          "【小红书 URL 解析】" in _TOOL_PROMPT_ADDENDUM)
    check("contains 'xhs.parse_url'",
          "xhs.parse_url" in _TOOL_PROMPT_ADDENDUM)
    check("contains '不主动爬'",
          "不主动爬" in _TOOL_PROMPT_ADDENDUM)


# ---------------------------------------------------------------------------
# 7. capability wrapper missing url
# ---------------------------------------------------------------------------

async def test_capability_missing_url():
    print("\n[xhs.parse_url capability — 空 url]")
    r = await xhs_cap.parse_url(url="")
    check("missing_url", r.get("error") == "missing_url")


async def test_capability_accepts_user_id():
    print("\n[xhs.parse_url capability — 接 user_id kwarg]")
    fake_client = await _mock_client_returning(_FakeResp(412, ""))
    with patch("backend.integrations.xiaohongshu.httpx.AsyncClient",
               return_value=fake_client):
        r = await xhs_cap.parse_url(
            url="https://www.xiaohongshu.com/explore/x",
            user_id="u1",
        )
        check("returns dict", isinstance(r, dict))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def amain():
    await test_parse_post_invalid_url()
    await test_parse_post_initial_state_path()
    await test_parse_post_og_fallback()
    await test_parse_post_blocked()
    await test_parse_post_parse_failed()
    await test_parse_post_non_200_other()
    await test_capability_missing_url()
    await test_capability_accepts_user_id()


def main():
    test_url_validation()
    test_parse_initial_state_basic()
    test_parse_initial_state_undefined()
    test_parse_initial_state_truncated()
    test_parse_initial_state_invalid()
    test_extract_note_path_noteDetailMap()
    test_extract_note_path_note_note()
    test_extract_note_path_noteData()
    test_extract_note_not_found()
    test_extract_og_meta()
    test_extract_og_meta_twitter_fallback()
    asyncio.run(amain())
    test_only_one_xhs_capability()
    test_description_redlines()
    test_addendum_redlines()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()

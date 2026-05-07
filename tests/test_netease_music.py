"""v3-H chunk 1 — NeteaseClient (web API + weapi crypto) 测试。

覆盖：
  - weapi_encrypt 输出结构合法（params=base64 / encSecKey=256 hex）
  - weapi_encrypt 双调相同 payload 输出不同（secret 是随机的）
  - 缺 cookie 调业务接口 → NeteaseAPIError
  - mock requests 验证 URL / headers / cookies / payload 包装
  - 业务 code != 200 → NeteaseAPIError
  - song normalize：搜索 / 歌单详情 两种 shape 都对齐
  - URL scheme 拼装合法

不依赖真实网易云账号 / 网络。
"""
import asyncio
import os
import re
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.integrations.netease_music as nm

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. weapi_encrypt 形状
# ---------------------------------------------------------------------------

def test_weapi_encrypt_shape():
    print("\n[netease — weapi_encrypt output shape]")
    out = nm.weapi_encrypt({"hello": "world"})
    check("has params + encSecKey", set(out.keys()) == {"params", "encSecKey"})
    # params 是 base64 字符串
    check("params is base64-ish", isinstance(out["params"], str) and len(out["params"]) > 0)
    # encSecKey 是 256 位 hex
    check(
        "encSecKey 256 hex chars",
        isinstance(out["encSecKey"], str) and bool(re.fullmatch(r"[0-9a-f]{256}", out["encSecKey"])),
    )


def test_weapi_encrypt_random():
    print("\n[netease — weapi_encrypt produces different secret each call]")
    a = nm.weapi_encrypt({"x": 1})
    b = nm.weapi_encrypt({"x": 1})
    check("same payload → different encSecKey", a["encSecKey"] != b["encSecKey"])
    check("same payload → different params", a["params"] != b["params"])


# ---------------------------------------------------------------------------
# 2. cookie 缺失保护
# ---------------------------------------------------------------------------

def test_no_cookie_raises():
    print("\n[netease — empty cookie blocks API calls]")
    client = nm.NeteaseClient(music_u="")
    check("has_credentials False", client.has_credentials is False)
    raised = False
    try:
        client._weapi_post("/v1/test", {})
    except nm.NeteaseAPIError as exc:
        raised = "cookie" in str(exc).lower() or "music_u" in str(exc).lower()
    check("missing cookie → NeteaseAPIError", raised)


# ---------------------------------------------------------------------------
# 3. mocked POST: URL / headers / cookies / body
# ---------------------------------------------------------------------------

def _mock_response(json_body: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


def test_weapi_post_request_shape():
    print("\n[netease — _weapi_post sends correct URL / headers / cookies]")
    client = nm.NeteaseClient(music_u="MOCK_COOKIE")

    captured = {}

    def fake_post(url, data=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return _mock_response({"code": 200, "data": {"hello": "world"}})

    with patch.object(nm.requests, "post", side_effect=fake_post):
        out = client._weapi_post("/v1/test", {"foo": "bar"})

    check("URL prefixed with /weapi", captured["url"].startswith("https://music.163.com/weapi/"))
    check("URL ends with path", captured["url"].endswith("/v1/test"))
    check("body has params + encSecKey", set((captured["data"] or {}).keys()) == {"params", "encSecKey"})
    check("UA mentions Chrome", "Chrome" in (captured["headers"] or {}).get("User-Agent", ""))
    check("Referer = music.163.com", (captured["headers"] or {}).get("Referer", "").startswith("https://music.163.com"))
    check("Origin set", (captured["headers"] or {}).get("Origin", "") == "https://music.163.com")
    check("MUSIC_U cookie sent", (captured["cookies"] or {}).get("MUSIC_U") == "MOCK_COOKIE")
    check("response data passed through", out.get("data", {}).get("hello") == "world")


def test_weapi_code_301_raises_invalid_cookie():
    print("\n[netease — code=301 (cookie invalid) raises]")
    client = nm.NeteaseClient(music_u="EXPIRED")

    with patch.object(
        nm.requests, "post",
        return_value=_mock_response({"code": 301, "msg": "需要登录"}),
    ):
        raised = None
        try:
            client._weapi_post("/x", {})
        except nm.NeteaseAPIError as exc:
            raised = exc
    check("301 → NeteaseAPIError", raised is not None)
    check("error mentions cookie", raised is not None and "cookie" in str(raised).lower())


def test_http_500_raises():
    print("\n[netease — HTTP 5xx raises]")
    client = nm.NeteaseClient(music_u="X")
    with patch.object(
        nm.requests, "post",
        return_value=_mock_response({"oops": "down"}, status=500),
    ):
        raised = None
        try:
            client._weapi_post("/x", {})
        except nm.NeteaseAPIError as exc:
            raised = exc
    check("HTTP 500 → NeteaseAPIError", raised is not None)
    check("error mentions HTTP", raised is not None and "HTTP" in str(raised))


def test_network_exception_raises():
    print("\n[netease — requests.RequestException → NeteaseAPIError]")
    import requests as _requests
    client = nm.NeteaseClient(music_u="X")
    with patch.object(
        nm.requests, "post",
        side_effect=_requests.ConnectionError("dns lookup failed"),
    ):
        raised = None
        try:
            client._weapi_post("/x", {})
        except nm.NeteaseAPIError as exc:
            raised = exc
    check("conn error wrapped", raised is not None)
    check("error mentions 网络", raised is not None and "网络" in str(raised))


# ---------------------------------------------------------------------------
# 4. 业务方法（基于 mock _weapi_post）
# ---------------------------------------------------------------------------

def test_my_playlists_normalises():
    print("\n[netease — my_playlists shape]")
    client = nm.NeteaseClient(music_u="X")
    client._user_id = 999  # 跳过 _ensure_user_id

    fake_resp = {
        "code": 200,
        "playlist": [
            {"id": 1, "name": "我喜欢的音乐", "trackCount": 50, "specialType": 5},
            {"id": 2, "name": "🏃 跑步专用", "trackCount": 23},
            {"id": 3},  # 非法但不应炸
        ],
    }
    with patch.object(client, "_weapi_post", return_value=fake_resp):
        out = client.my_playlists()
    check("returned 3 entries", len(out) == 3)
    check("first is_liked True", out[0]["is_liked"] is True)
    check("second is_liked False", out[1]["is_liked"] is False)
    check("emoji 名字保留", out[1]["name"] == "🏃 跑步专用")
    check("missing fields default", out[2]["name"] == "" and out[2]["track_count"] == 0)


def test_search_song_shape():
    print("\n[netease — search song normalises]")
    client = nm.NeteaseClient(music_u="X")
    fake_resp = {
        "code": 200,
        "result": {
            "songs": [
                {
                    "id": 100,
                    "name": "夜空中最亮的星",
                    "ar": [{"name": "逃跑计划"}],
                    "al": {"name": "世界"},
                },
            ],
        },
    }
    with patch.object(client, "_weapi_post", return_value=fake_resp):
        out = client.search("夜空")
    check("returned 1 song", len(out) == 1)
    check("song id", out[0]["id"] == 100)
    check("artists list", out[0]["artists"] == ["逃跑计划"])
    check("album name", out[0]["album"] == "世界")


def test_daily_recommend_uses_dailySongs_path():
    print("\n[netease — daily_recommend reads data.dailySongs]")
    client = nm.NeteaseClient(music_u="X")
    fake_resp = {
        "code": 200,
        "data": {
            "dailySongs": [
                {"id": 1, "name": "A", "ar": [{"name": "X"}], "al": {"name": "Y"}},
                {"id": 2, "name": "B", "ar": [{"name": "Z"}]},
            ],
        },
    }
    with patch.object(client, "_weapi_post", return_value=fake_resp):
        out = client.daily_recommend()
    check("2 songs", len(out) == 2)
    check("first artist", out[0]["artists"] == ["X"])
    check("second album empty (al missing)", out[1]["album"] == "")


# ---------------------------------------------------------------------------
# 5. URL scheme
# ---------------------------------------------------------------------------

def test_url_scheme():
    print("\n[netease — orpheus URL scheme builder]")
    check(
        "song scheme",
        nm.NeteaseClient.play_url_scheme("song", 12345) == "orpheus://song/12345",
    )
    check(
        "playlist scheme",
        nm.NeteaseClient.play_url_scheme("playlist", 999) == "orpheus://playlist/999",
    )
    raised = False
    try:
        nm.NeteaseClient.play_url_scheme("bogus", 1)
    except ValueError:
        raised = True
    check("unsupported kind → ValueError", raised)


# ---------------------------------------------------------------------------
# 6. health_check
# ---------------------------------------------------------------------------

async def test_health_check_no_cookie():
    print("\n[netease — health_check: no cookie warn]")
    nm._reset_client_cache()
    with patch.object(nm.settings, "netease_music_u", ""):
        h = await nm.health_check()
    check("status warn", h["status"] == "warn")
    check("提示 NETEASE_MUSIC_U", "NETEASE_MUSIC_U" in (h.get("error") or ""))
    nm._reset_client_cache()


async def test_health_check_with_cookie_ok():
    print("\n[netease — health_check: valid cookie healthy]")
    nm._reset_client_cache()
    with patch.object(nm.settings, "netease_music_u", "VALID"):
        client = nm.get_client()
        # _ensure_user_id 用 _weapi_post → mock _weapi_post
        with patch.object(client, "_weapi_post", return_value={"code": 200, "profile": {"userId": 42}}):
            h = await nm.health_check()
    check("status healthy", h["status"] == "healthy")
    check("user_id reflected", h.get("user_id") == 42)
    nm._reset_client_cache()


async def test_health_check_invalid_cookie_warn():
    print("\n[netease — health_check: invalid cookie warn]")
    nm._reset_client_cache()
    with patch.object(nm.settings, "netease_music_u", "BAD"):
        client = nm.get_client()
        with patch.object(client, "_weapi_post", side_effect=nm.NeteaseAPIError("cookie 失效")):
            h = await nm.health_check()
    check("status warn", h["status"] == "warn")
    check("error 提到 cookie", "cookie" in (h.get("error") or "").lower())
    nm._reset_client_cache()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    test_weapi_encrypt_shape()
    test_weapi_encrypt_random()
    test_no_cookie_raises()
    test_weapi_post_request_shape()
    test_weapi_code_301_raises_invalid_cookie()
    test_http_500_raises()
    test_network_exception_raises()
    test_my_playlists_normalises()
    test_search_song_shape()
    test_daily_recommend_uses_dailySongs_path()
    test_url_scheme()
    await test_health_check_no_cookie()
    await test_health_check_with_cookie_ok()
    await test_health_check_invalid_cookie_warn()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())

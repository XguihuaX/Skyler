"""V4-fan chunk 1 — splash art upload / delete endpoints.

Run:
    .venv/bin/python tests/test_splash_art.py

设计:
- 用 ``tempfile.TemporaryDirectory`` 做 ``_SPLASH_ART_DIR``,monkey-patch
  ``backend.routes.characters_api._SPLASH_ART_DIR`` 让 endpoint 写到隔离
  目录,不污染真实 ``frontend/public/splash-art/``。
- 高位 character_id (800 段),避开 background test 用的 700 段、
  character_state test 用的 600 段、app 默认的 1-99 段。
- TestClient 走完整 FastAPI multipart parsing,贴近真机表现。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.database import engine, init_db
from backend.database.migrations.v3_5_chunk5a_character_background import (
    run_migration as run_chunk5a,
)
from backend.database.migrations.v4_fan_chunk1_splash_art import (
    run_migration as run_v4_fan_chunk1,
)
import backend.routes.characters_api as _chars_api
from backend.routes.characters_api import router as _chars_router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []

TEST_ID_START = 800

# 最小合法 PNG(8 字节签名)+ JPEG(2 字节 SOI)+ WebP(12 字节 RIFF/WEBP
# 头)。endpoint 不解码图像,只看 MIME / 扩展名,所以"形似即可",不需要
# 真正的解码合法。
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_WEBP_BYTES = b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(_chars_router, prefix="/api")
    return app


async def _setup_db() -> None:
    await init_db()
    # background 列(_to_dict 返回字段需要;migration 幂等)
    await run_chunk5a()
    # 本 stage migration
    await run_v4_fan_chunk1()
    # 清掉本测试段的残留(按 id 范围 + 名字前缀)
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM characters WHERE id >= :i AND id < :j"
        ), {"i": TEST_ID_START, "j": TEST_ID_START + 100})
        await conn.execute(text(
            "DELETE FROM characters WHERE name LIKE '_splash_test_%'"
        ))


async def _cleanup_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM characters WHERE id >= :i AND id < :j"
        ), {"i": TEST_ID_START, "j": TEST_ID_START + 100})
        await conn.execute(text(
            "DELETE FROM characters WHERE name LIKE '_splash_test_%'"
        ))


async def _insert_test_char(char_id: int, name: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO characters (id, name, persona) "
            "VALUES (:id, :name, :persona)"
        ), {"id": char_id, "name": name, "persona": "test"})


async def _read_splash_url(char_id: int) -> str | None:
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT splash_art_url FROM characters WHERE id = :id"
        ), {"id": char_id})).fetchone()
    return row[0] if row else None


def _patch_splash_dir(tmpdir: Path) -> None:
    """Redirect endpoint's _SPLASH_ART_DIR to tmpdir."""
    _chars_api._SPLASH_ART_DIR = tmpdir


# ---------------------------------------------------------------------------
# 1. test_upload_valid_png
# ---------------------------------------------------------------------------

def test_upload_valid_png() -> None:
    print("\n[test_upload_valid_png — happy path PNG]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 1
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_png")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())
        r = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("hero.png", _PNG_BYTES, "image/png")},
        )
        check("status 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        body = r.json()
        check("character_id echoed", body.get("character_id") == char_id)
        check("splash_art_url == /splash-art/<id>.png",
              body.get("splash_art_url") == f"/splash-art/{char_id}.png",
              f"got {body.get('splash_art_url')!r}")

        # 文件落盘
        target = splash_dir / f"{char_id}.png"
        check("file written to disk", target.exists())
        check("file bytes match", target.read_bytes() == _PNG_BYTES)

        # DB 写入
        url = asyncio.get_event_loop().run_until_complete(
            _read_splash_url(char_id)
        )
        check("DB splash_art_url persisted", url == f"/splash-art/{char_id}.png")


# ---------------------------------------------------------------------------
# 2. test_upload_valid_jpeg
# ---------------------------------------------------------------------------

def test_upload_valid_jpeg() -> None:
    print("\n[test_upload_valid_jpeg — happy path JPEG (.jpeg → .jpg)]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 2
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_jpeg")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())
        r = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("hero.jpeg", _JPEG_BYTES, "image/jpeg")},
        )
        check("status 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        body = r.json()
        check("ext normalized to .jpg",
              body.get("splash_art_url") == f"/splash-art/{char_id}.jpg",
              f"got {body.get('splash_art_url')!r}")
        check("file at .jpg path",
              (splash_dir / f"{char_id}.jpg").exists())


# ---------------------------------------------------------------------------
# 3. test_upload_valid_webp
# ---------------------------------------------------------------------------

def test_upload_valid_webp() -> None:
    print("\n[test_upload_valid_webp — happy path WebP]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 3
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_webp")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())
        r = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("hero.webp", _WEBP_BYTES, "image/webp")},
        )
        check("status 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        body = r.json()
        check("ext .webp",
              body.get("splash_art_url") == f"/splash-art/{char_id}.webp")
        check("file at .webp path",
              (splash_dir / f"{char_id}.webp").exists())


# ---------------------------------------------------------------------------
# 4. test_upload_too_large_6mb
# ---------------------------------------------------------------------------

def test_upload_too_large_6mb() -> None:
    print("\n[test_upload_too_large_6mb — 413]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 4
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_oversize")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        big_blob = b"\x89PNG\r\n\x1a\n" + b"\x00" * (6 * 1024 * 1024)
        client = TestClient(_build_app())
        r = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("huge.png", big_blob, "image/png")},
        )
        check("status 413", r.status_code == 413,
              f"got {r.status_code}: {r.text[:120]}")
        check("error mentions limit",
              "limit" in r.text.lower() or "exceeds" in r.text.lower())

        # 文件不应该落盘
        check("no file written on rejection",
              not (splash_dir / f"{char_id}.png").exists())

        # DB url 也不应被写
        url = asyncio.get_event_loop().run_until_complete(
            _read_splash_url(char_id)
        )
        check("DB splash_art_url stayed NULL", url is None,
              f"got {url!r}")


# ---------------------------------------------------------------------------
# 5. test_upload_unsupported_txt
# ---------------------------------------------------------------------------

def test_upload_unsupported_txt() -> None:
    print("\n[test_upload_unsupported_txt — 415]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 5
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_txt")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())
        r = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("readme.txt", b"hello", "text/plain")},
        )
        check("status 415", r.status_code == 415,
              f"got {r.status_code}: {r.text[:120]}")
        check("error mentions unsupported / type",
              "unsupported" in r.text.lower() or "type" in r.text.lower())


# ---------------------------------------------------------------------------
# 6. test_upload_character_not_found
# ---------------------------------------------------------------------------

def test_upload_character_not_found() -> None:
    print("\n[test_upload_character_not_found — 404]")
    asyncio.get_event_loop().run_until_complete(_setup_db())

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())
        # id 99999 — 不可能存在(本测试段 800-899,主表也不会撞)
        r = client.post(
            "/api/characters/99999/splash-art",
            files={"file": ("a.png", _PNG_BYTES, "image/png")},
        )
        check("status 404", r.status_code == 404,
              f"got {r.status_code}: {r.text[:120]}")


# ---------------------------------------------------------------------------
# 7. test_upload_replaces_old_different_ext
# ---------------------------------------------------------------------------

def test_upload_replaces_old_different_ext() -> None:
    print("\n[test_upload_replaces_old_different_ext — .jpg → .png cleanup]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 7
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_replace")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())

        # 1) upload .jpg
        r1 = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("v1.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        check("first upload 200", r1.status_code == 200)
        check("v1 .jpg on disk", (splash_dir / f"{char_id}.jpg").exists())

        # 2) upload .png — 旧 .jpg 必须被清,DB 切到 .png
        r2 = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("v2.png", _PNG_BYTES, "image/png")},
        )
        check("second upload 200", r2.status_code == 200)
        check("v2 .png on disk", (splash_dir / f"{char_id}.png").exists())
        check("old .jpg deleted",
              not (splash_dir / f"{char_id}.jpg").exists())

        # DB url 应指向 .png
        url = asyncio.get_event_loop().run_until_complete(
            _read_splash_url(char_id)
        )
        check("DB url updated to .png",
              url == f"/splash-art/{char_id}.png", f"got {url!r}")


# ---------------------------------------------------------------------------
# 8. test_upload_tauri_empty_mime_fallback
# ---------------------------------------------------------------------------

def test_upload_tauri_empty_mime_fallback() -> None:
    print("\n[test_upload_tauri_empty_mime_fallback — content_type='' + .png]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 8
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_tauri")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())
        # Starlette TestClient 三元组里把 content_type 设成
        # "application/octet-stream"(空字符串会被 starlette 转成默认值);
        # 这是 Tauri WebView 偶发的实际表现 —— MIME 不可信、扩展名兜底
        r = client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("hero.png", _PNG_BYTES, "application/octet-stream")},
        )
        check("status 200 (ext fallback)", r.status_code == 200,
              f"got {r.status_code}: {r.text[:120]}")
        body = r.json()
        check("ext resolved from filename .png",
              body.get("splash_art_url") == f"/splash-art/{char_id}.png",
              f"got {body.get('splash_art_url')!r}")


# ---------------------------------------------------------------------------
# 9. test_delete_splash_art
# ---------------------------------------------------------------------------

def test_delete_splash_art() -> None:
    print("\n[test_delete_splash_art — DELETE removes file + DB NULL]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    char_id = TEST_ID_START + 9
    asyncio.get_event_loop().run_until_complete(
        _insert_test_char(char_id, "_splash_test_delete")
    )

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())

        # 先上传一张
        client.post(
            f"/api/characters/{char_id}/splash-art",
            files={"file": ("a.png", _PNG_BYTES, "image/png")},
        )
        check("setup: file on disk", (splash_dir / f"{char_id}.png").exists())

        # 删
        r = client.delete(f"/api/characters/{char_id}/splash-art")
        check("status 200", r.status_code == 200,
              f"got {r.status_code}: {r.text[:120]}")
        body = r.json()
        check("body deleted=true", body.get("deleted") is True)
        check("body character_id echoed",
              body.get("character_id") == char_id)

        # 文件已删
        check("file removed from disk",
              not (splash_dir / f"{char_id}.png").exists())

        # DB url == NULL
        url = asyncio.get_event_loop().run_until_complete(
            _read_splash_url(char_id)
        )
        check("DB splash_art_url == NULL", url is None, f"got {url!r}")


# ---------------------------------------------------------------------------
# 10. test_delete_character_not_found
# ---------------------------------------------------------------------------

def test_delete_character_not_found() -> None:
    print("\n[test_delete_character_not_found — DELETE 不存在 char → 404]")
    asyncio.get_event_loop().run_until_complete(_setup_db())

    with tempfile.TemporaryDirectory() as td:
        splash_dir = Path(td) / "splash-art"
        splash_dir.mkdir()
        _patch_splash_dir(splash_dir)

        client = TestClient(_build_app())
        r = client.delete("/api/characters/99999/splash-art")
        check("status 404", r.status_code == 404,
              f"got {r.status_code}: {r.text[:120]}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    orig_dir = _chars_api._SPLASH_ART_DIR
    try:
        test_upload_valid_png()
        test_upload_valid_jpeg()
        test_upload_valid_webp()
        test_upload_too_large_6mb()
        test_upload_unsupported_txt()
        test_upload_character_not_found()
        test_upload_replaces_old_different_ext()
        test_upload_tauri_empty_mime_fallback()
        test_delete_splash_art()
        test_delete_character_not_found()
    finally:
        _chars_api._SPLASH_ART_DIR = orig_dir
        asyncio.get_event_loop().run_until_complete(_cleanup_db())

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

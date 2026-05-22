"""v4.0 voice greeting · backend/routes/voice_lines.py CRUD + integration test。

per PM dispatch(2026-05-22)smoke 要求:
- CRUD 单测 + 集成验 multipart 上传 + 落盘 + duration 提取 + 删除清理
- 空 list random 行为(404)
- 格式 / 大小 invalid

跑法:
    .venv/bin/python tests/test_voice_lines.py

策略:用 FastAPI TestClient + 现 momoos.db(per characters_api 测试同款),
插 TEST_ 前缀 voice_lines / 测完清理。不写新 character row(用现 cid=2
八重神子 / cid=4 凝光 等);上传文件 fixtures 用 inline minimal WAV
header(45-byte minimum WAV)避免依赖外部 audio file。
"""
from __future__ import annotations

import io
import os
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from sqlalchemy import text as sql_text  # noqa: E402
import asyncio  # noqa: E402

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []
client = TestClient(app)

# 用一个 dogfood cid(non-Mai · 避免影响 cid=101 真活路径)
TEST_CID = 4  # 凝光 · 现 voice_model 空,test 用安全


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _make_minimal_wav_bytes(duration_sec: float = 0.5,
                            sample_rate: int = 8000) -> bytes:
    """生成最小 valid WAV(silent mono PCM 16bit)。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        n_samples = int(sample_rate * duration_sec)
        # silent samples
        wav.writeframes(struct.pack("<%dh" % n_samples, *([0] * n_samples)))
    return buf.getvalue()


def _cleanup_test_rows() -> None:
    """删 TEST_CID 下所有 voice lines + DB rows + files。"""
    from backend.database import engine as db_engine

    async def _run():
        async with db_engine.begin() as conn:
            rows = (await conn.execute(sql_text(
                "SELECT audio_path FROM character_voice_lines WHERE character_id = :cid"
            ), {"cid": TEST_CID})).fetchall()
            for r in rows:
                p = (Path(__file__).resolve().parent.parent
                     / "backend" / "static" / "voice_lines" / r[0])
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
            await conn.execute(sql_text(
                "DELETE FROM character_voice_lines WHERE character_id = :cid"
            ), {"cid": TEST_CID})
    asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────
# 1. character 不存在 → 404
# ─────────────────────────────────────────────────────────────────────
def test_404_unknown_character():
    print("\n[1.1] POST 未知 character → 404")
    wav = _make_minimal_wav_bytes(0.3)
    resp = client.post(
        "/api/character/99999/voice_lines",
        files={"file": ("test.wav", wav, "audio/wav")},
    )
    check("POST unknown cid → 404", resp.status_code == 404,
          detail=f"got {resp.status_code}")

    print("[1.2] GET list 未知 cid → 404")
    resp = client.get("/api/character/99999/voice_lines")
    check("GET list unknown cid → 404", resp.status_code == 404)

    print("[1.3] GET random 未知 cid → 404")
    resp = client.get("/api/character/99999/voice_lines/random")
    check("GET random unknown cid → 404", resp.status_code == 404)


# ─────────────────────────────────────────────────────────────────────
# 2. 空 list / random → 404
# ─────────────────────────────────────────────────────────────────────
def test_empty_list_random():
    _cleanup_test_rows()
    print("\n[2.1] GET list 空 → 200 count=0")
    resp = client.get(f"/api/character/{TEST_CID}/voice_lines")
    check("status 200", resp.status_code == 200)
    body = resp.json() if resp.status_code == 200 else {}
    check("count == 0", body.get("count") == 0)
    check("items == []", body.get("items") == [])

    print("[2.2] GET random 空 → 404")
    resp = client.get(f"/api/character/{TEST_CID}/voice_lines/random")
    check("空 list random → 404", resp.status_code == 404)


# ─────────────────────────────────────────────────────────────────────
# 3. POST upload · happy path · multipart + duration + DB INSERT
# ─────────────────────────────────────────────────────────────────────
def test_upload_happy_path():
    _cleanup_test_rows()
    print("\n[3.1] POST upload 最小 WAV · duration extract + DB INSERT")
    wav = _make_minimal_wav_bytes(0.5, sample_rate=8000)  # 0.5s
    resp = client.post(
        f"/api/character/{TEST_CID}/voice_lines",
        files={"file": ("test_happy.wav", wav, "audio/wav")},
        data={"text_description": "test description",
              "language": "ja"},
    )
    check("status 200", resp.status_code == 200,
          detail=f"got {resp.status_code} body={resp.text[:200]}")
    if resp.status_code != 200:
        return
    body = resp.json()
    check("含 id", "id" in body and isinstance(body["id"], int))
    check("audio_path 形如 '<cid>/<uuid>.wav'",
          body["audio_path"].startswith(f"{TEST_CID}/")
          and body["audio_path"].endswith(".wav"))
    check("audio_url 形如 '/static/voice_lines/<cid>/<uuid>.wav'",
          body["audio_url"] == f"/static/voice_lines/{body['audio_path']}")
    check("text_description 写入", body["text_description"] == "test description")
    check("language 写入", body["language"] == "ja")
    # duration_ms 在 mutagen 提取 ~500ms ± 容差
    dur = body.get("duration_ms")
    check(f"duration_ms ~500ms got {dur}",
          dur is not None and 400 <= dur <= 600,
          detail=f"got {dur}")

    # File 真落盘 verify
    full_path = (Path(__file__).resolve().parent.parent
                 / "backend" / "static" / "voice_lines" / body["audio_path"])
    check("file 落盘存在", full_path.exists(),
          detail=f"path={full_path}")
    check("file size > 0", full_path.exists() and full_path.stat().st_size > 0)


# ─────────────────────────────────────────────────────────────────────
# 4. GET list 含上传的 row
# ─────────────────────────────────────────────────────────────────────
def test_list_after_upload():
    # 假设 test_upload_happy_path 跑过留了 1 row
    print("\n[4] GET list 含上传 row")
    resp = client.get(f"/api/character/{TEST_CID}/voice_lines")
    check("status 200", resp.status_code == 200)
    body = resp.json() if resp.status_code == 200 else {}
    check(f"count >= 1(实际 {body.get('count')})", body.get("count", 0) >= 1)
    if body.get("count", 0) > 0:
        item = body["items"][0]
        check("item 含 id", "id" in item)
        check("item 含 audio_url", "audio_url" in item
              and item["audio_url"].startswith("/static/voice_lines/"))


# ─────────────────────────────────────────────────────────────────────
# 5. GET random · 非空时返 1 个
# ─────────────────────────────────────────────────────────────────────
def test_random_non_empty():
    print("\n[5] GET random 非空 → 200 + 1 item")
    resp = client.get(f"/api/character/{TEST_CID}/voice_lines/random")
    check("status 200", resp.status_code == 200,
          detail=f"got {resp.status_code}")
    if resp.status_code == 200:
        body = resp.json()
        check("含 audio_url", "audio_url" in body
              and body["audio_url"].startswith("/static/voice_lines/"))
        check("character_id == TEST_CID",
              body.get("character_id") == TEST_CID)


# ─────────────────────────────────────────────────────────────────────
# 6. DELETE · del file + DB row
# ─────────────────────────────────────────────────────────────────────
def test_delete():
    print("\n[6] DELETE voice line · 删 file + DB row")
    # 上传一个新 line 然后删
    wav = _make_minimal_wav_bytes(0.3)
    resp = client.post(
        f"/api/character/{TEST_CID}/voice_lines",
        files={"file": ("test_delete.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200, f"setup upload failed: {resp.text}"
    line_id = resp.json()["id"]
    audio_path = resp.json()["audio_path"]
    full_path = (Path(__file__).resolve().parent.parent
                 / "backend" / "static" / "voice_lines" / audio_path)
    check("setup · file 存在", full_path.exists())

    # DELETE
    resp = client.delete(
        f"/api/character/{TEST_CID}/voice_lines/{line_id}",
    )
    check("DELETE status 200", resp.status_code == 200)
    body = resp.json()
    check("deleted_id matches", body.get("deleted_id") == line_id)
    check("file 已 unlink", not full_path.exists())

    # GET list 不该含此 id
    resp = client.get(f"/api/character/{TEST_CID}/voice_lines")
    body = resp.json()
    ids = [it["id"] for it in body.get("items", [])]
    check("DB row 已删", line_id not in ids)


def test_delete_unknown_id():
    print("\n[6.1] DELETE 未知 id → 404")
    resp = client.delete(f"/api/character/{TEST_CID}/voice_lines/99999")
    check("DELETE unknown line_id → 404", resp.status_code == 404)


# ─────────────────────────────────────────────────────────────────────
# 7. 格式 / 大小校验
# ─────────────────────────────────────────────────────────────────────
def test_format_validation():
    print("\n[7.1] POST 非 audio 格式 → 415")
    resp = client.post(
        f"/api/character/{TEST_CID}/voice_lines",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    check("text/plain 非 audio → 415", resp.status_code == 415,
          detail=f"got {resp.status_code}")

    print("[7.2] POST > 5MB → 413")
    big = b"\x00" * (5 * 1024 * 1024 + 100)  # > 5MB
    resp = client.post(
        f"/api/character/{TEST_CID}/voice_lines",
        files={"file": ("big.wav", big, "audio/wav")},
    )
    check("> 5MB → 413", resp.status_code == 413,
          detail=f"got {resp.status_code}")


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────
def main():
    try:
        test_404_unknown_character()
        test_empty_list_random()
        test_upload_happy_path()
        test_list_after_upload()
        test_random_non_empty()
        test_delete()
        test_delete_unknown_id()
        test_format_validation()
    finally:
        _cleanup_test_rows()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()

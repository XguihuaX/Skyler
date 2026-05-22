"""v4.0 voice greeting · seed 6 Mai voice lines to cid=101(一次性脚本)。

per PM dispatch(2026-05-22)· feature 主 commit ship 后立刻跑一次,让 PM
到酒店打开立绘馆点 Mai 就能听见 Mai 招呼。

源:scripts/fish_probe_outputs/ 现成 Mai WAV(part 1 sweep + e2e marker 测试
ship 的 ja TTS 真合成产物;Mai 5min reference + fish s2-pro Japanese voice)。

6 seed files + text_description(per fish_marker_e2e_smoke.py MAI_CANON_CASES
+ fish_param_sweep.py S2/S3 texts):

  1. INV9_param_T02_S2.wav
     "私、桜島麻衣。桜島の桜、麻衣の衣。簡単でしょう?"  (Mai 自我介绍 canon)

  2. INV9_param_T02_S3.wav
     "[teasing] あら、来たのね。"  (短 + teasing marker)

  3. INV9_e2e_fish_composed.wav
     "[composed]「君、今日は元気がないね。」"  (冷静档)

  4. INV9_e2e_fish_sarcastic.wav
     "[sarcastic]「あら、すごいじゃない。」"  (挖苦档)

  5. INV9_e2e_fish_teasing.wav
     "[teasing]「ほら、また当たったでしょ。」"  (挖苦档 + 长)

  6. INV9_e2e_fish_gentle.wav
     "[gentle]「あんまり無理しないでね。」"  (温柔档)

跑法:
    .venv/bin/python scripts/seed_mai_voice_lines.py

幂等性:脚本不查重 — 若 cid=101 已有 6 条同样描述的 row,会**重复** seed
6 条(累积 12 条)。CC 故意不查重(per seed script convention 是 fresh
state);若需重 seed,先手动 DELETE 旧 row + files。
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOURCE_DIR = ROOT / "scripts" / "fish_probe_outputs"
TARGET_DIR = ROOT / "backend" / "static" / "voice_lines" / "101"

# 6 seed entries · (source_filename, text_description)
SEEDS: list[tuple[str, str]] = [
    ("INV9_param_T02_S2.wav",
     "私、桜島麻衣。桜島の桜、麻衣の衣。簡単でしょう?"),
    ("INV9_param_T02_S3.wav",
     "[teasing] あら、来たのね。"),
    ("INV9_e2e_fish_composed.wav",
     "[composed]「君、今日は元気がないね。」"),
    ("INV9_e2e_fish_sarcastic.wav",
     "[sarcastic]「あら、すごいじゃない。」"),
    ("INV9_e2e_fish_teasing.wav",
     "[teasing]「ほら、また当たったでしょ。」"),
    ("INV9_e2e_fish_gentle.wav",
     "[gentle]「あんまり無理しないでね。」"),
]

CHARACTER_ID = 101  # 樱岛麻衣


def _extract_duration_ms(file_path: Path) -> int | None:
    """复用 voice_lines.py robust 实现(Fish WAV header bug 兜底)。"""
    from backend.routes.voice_lines import extract_audio_duration_ms
    return extract_audio_duration_ms(file_path)


async def main() -> int:
    from backend.database import engine as db_engine
    from sqlalchemy import text as sql_text

    # 检查 character 存在
    async with db_engine.begin() as conn:
        row = (await conn.execute(
            sql_text("SELECT name FROM characters WHERE id = :cid"),
            {"cid": CHARACTER_ID},
        )).first()
        if row is None:
            print(f"❌ character_id={CHARACTER_ID} not found in DB")
            return 1
        char_name = row[0]
        print(f"Target character: cid={CHARACTER_ID} name={char_name!r}")

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    seeded_ids: list[int] = []
    for src_filename, desc in SEEDS:
        src_path = SOURCE_DIR / src_filename
        if not src_path.exists():
            print(f"  [SKIP] source missing: {src_path.relative_to(ROOT)}")
            continue

        # 生成新 uuid filename 落到 target
        new_uuid = uuid.uuid4().hex
        target_name = f"{new_uuid}.wav"
        target_path = TARGET_DIR / target_name
        shutil.copy2(src_path, target_path)

        duration_ms = _extract_duration_ms(target_path)
        rel_audio_path = f"{CHARACTER_ID}/{target_name}"

        async with db_engine.begin() as conn:
            result = await conn.execute(sql_text("""
                INSERT INTO character_voice_lines
                    (character_id, audio_path, text_description, language, duration_ms)
                VALUES (:cid, :path, :desc, :lang, :dur)
            """), {
                "cid": CHARACTER_ID,
                "path": rel_audio_path,
                "desc": desc,
                "lang": "ja",
                "dur": duration_ms,
            })
            new_id = result.lastrowid
            seeded_ids.append(new_id)

        print(f"  ✅ seeded id={new_id} · {duration_ms}ms · "
              f"{rel_audio_path} · {desc[:40]!r}")

    print(f"\n[done] Seeded {len(seeded_ids)} voice lines to cid={CHARACTER_ID}")
    print(f"       ids = {seeded_ids}")
    print(f"       dir = {TARGET_DIR.relative_to(ROOT)}/")

    # Verify · GET list 看
    async with db_engine.begin() as conn:
        rows = (await conn.execute(sql_text("""
            SELECT id, text_description, duration_ms
            FROM character_voice_lines
            WHERE character_id = :cid
            ORDER BY id
        """), {"cid": CHARACTER_ID})).fetchall()
    print(f"\n[verify] DB has {len(rows)} rows for cid={CHARACTER_ID}:")
    for r in rows:
        print(f"  id={r[0]} dur={r[2]}ms desc={r[1][:50]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

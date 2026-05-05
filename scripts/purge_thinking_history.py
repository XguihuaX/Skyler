"""One-shot script: purge ``<thinking>...</thinking>`` blocks from existing
chat_history rows.

This is a v3-E1 Step Z cleanup. v3-F introduced ``<thinking>`` tags but the
persistence layer was not updated until commit ``be0c6f4`` (Step Z.1). Rows
written between v3-F and ``be0c6f4`` contain raw thinking blocks; the front
end's defensive strip hides them at render time but they remain in DB,
costing storage and risking false positives in future ``profile_summary``
rewrites or long-term memory vectorization.

Usage
-----
    python -m scripts.purge_thinking_history [--dry-run]

Default mode actually updates the DB. ``--dry-run`` prints what would
change without writing.

Idempotent: running multiple times has no further effect (already-clean
rows pass through ``re.sub`` unchanged and are skipped).

Safety
------
- Empty-result protection: if stripping would leave the row content empty
  (only thinking, no body), the original is kept and the row is logged.
  Empty assistant content has weird downstream effects (renders as a blank
  bubble); better to keep the polluted version visible until manually
  inspected.
- The script only modifies ``content``; ``role`` / ``kind`` /
  ``interrupted_at`` etc. untouched.
- Take a manual ``cp momoos.db momoos.db.bak-pre-thinking-purge`` before
  running for real. The backup is **not** committed (file extension does
  not match the ``*.db`` gitignore glob — delete it manually after
  verification).
"""
from __future__ import annotations

import asyncio
import re
import sys

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.database.models import ChatHistory


# 跨行匹配（DOTALL）；非贪婪；尾随空白一并吞掉避免清完留下孤立换行
THINKING_PATTERN = re.compile(
    r"<thinking>.*?</thinking>\s*", re.DOTALL | re.IGNORECASE
)


async def main(dry_run: bool) -> None:
    cleaned = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ChatHistory).where(ChatHistory.content.like("%<thinking>%"))
        )
        rows = list(result.scalars().all())

        if not rows:
            print("No rows with <thinking> tags found. Nothing to clean.")
            return

        print(f"Found {len(rows)} rows containing <thinking> tags.")

        for row in rows:
            cleaned_content = THINKING_PATTERN.sub("", row.content)

            # 没有真正剥掉东西（罕见；可能是 <thinking> 字符串出现在 body 而无闭合）
            if cleaned_content == row.content:
                print(f"  Row id={row.id}: pattern matched LIKE but no substring removed, skipping")
                skipped += 1
                continue

            # 防御：剥完为空 → 保留原文（避免 chat_history.content NOT NULL 之外，
            # 也避免渲染层出现 zero-width 气泡）
            if not cleaned_content.strip():
                print(
                    f"  Row id={row.id}: would be empty after strip, KEEPING original"
                )
                skipped += 1
                continue

            print(
                f"  Row id={row.id}: {len(row.content)} chars -> "
                f"{len(cleaned_content)} chars"
            )

            if not dry_run:
                row.content = cleaned_content
                cleaned += 1

        if not dry_run:
            await session.commit()

    if dry_run:
        # dry-run 数字 = 真跑会清的行 = 全部找到的 - 跳过的
        would_clean = len(rows) - skipped
        print(f"\nDry run: would clean {would_clean} rows, skip {skipped}")
    else:
        print(f"\nCleaned {cleaned} rows, skipped {skipped}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry_run))

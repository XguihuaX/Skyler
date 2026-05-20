"""migrate ai_providers.model prefix: openai/ <-> dashscope/ for vendor=qwen LLM rows.

INV-5 §5 Phase 4 step 2/4 — 切 dashscope/ prefix 让 LiteLLM 走原生 DashScope
provider 路径,以便 Phase 3 注入的 cache_control marker pass-through 给端点
(T2 实证 1214 cached_tokens 完美命中)。

设计:
- **dry-run default**:不带 ``--apply`` 时只 SELECT 显示要改什么,**不动 DB**
- **idempotent**:UPDATE WHERE model=:old_value,已切过的行 rowcount=0
  无副作用,可重复运行不报错
- **rollback**:``--rollback`` flag 反向(dashscope/ → openai/),Phase 4 真机
  回归出问题秒退
- **scope 默认**:仅切 ``is_active=True`` 一行(默认行为对齐 brief);
  ``--all`` 切所有 vendor=qwen 且 model 含目标 prefix 的 enabled 行
- **单事务**:UPDATE 全部成功 / 全部回滚,不留半截
- **pre/post SELECT**:跑前显示当前状态,跑后 verify 写入

跑法:
  dry-run:           .venv/bin/python scripts/migrate_provider_prefix.py
  forward all qwen:  .venv/bin/python scripts/migrate_provider_prefix.py --apply --all
  forward only active: .venv/bin/python scripts/migrate_provider_prefix.py --apply
  rollback:          .venv/bin/python scripts/migrate_provider_prefix.py --apply --rollback [--all]

exit codes:
  0 — apply ok / nothing to do
  2 — dry-run finished, --apply not given
  3 — error / sql failed (transaction rolled back)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from backend.database import engine


async def _list_qwen_rows(conn):
    return (await conn.execute(text(
        "SELECT id, vendor_id, type, name, model, enabled, is_active "
        "FROM ai_providers WHERE type='llm' AND vendor_id='qwen' "
        "ORDER BY id"
    ))).fetchall()


def _classify(rows, src_prefix: str, also_all: bool):
    """Return (display_rows, targets)。

    display_rows: 所有 qwen LLM 行的展示元组(含 tag list)
    targets: 即将 UPDATE 的行 [(id, old_model, new_model)] 集合
    """
    display = []
    targets = []
    for r in rows:
        id_, vendor, type_, name, model, enabled, is_active = r
        hits_prefix = model.startswith(src_prefix)
        will_change = hits_prefix and bool(enabled) and (also_all or bool(is_active))
        tags = []
        if is_active:
            tags.append("ACTIVE")
        if not enabled:
            tags.append("disabled")
        if hits_prefix:
            tags.append(f"prefix={src_prefix}")
        else:
            tags.append("prefix=OTHER")
        if will_change:
            tags.append("WILL-CHANGE")
        display.append((id_, vendor, model, enabled, is_active, tags))
        if will_change:
            new_model = src_prefix.replace(
                src_prefix, ""  # strip src
            )  # placeholder; recomputed below
    # recompute targets cleanly
    targets = []
    for r in rows:
        id_, vendor, type_, name, model, enabled, is_active = r
        if not model.startswith(src_prefix):
            continue
        if not enabled:
            continue
        if not (also_all or is_active):
            continue
        targets.append((id_, model))
    return display, targets


async def _verify(conn, ids: list[int]) -> dict[int, str]:
    """Read back ids → current model dict."""
    out = {}
    for tid in ids:
        row = (await conn.execute(text(
            "SELECT model FROM ai_providers WHERE id = :id"
        ), {"id": tid})).first()
        out[tid] = row[0] if row else None
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Migrate ai_providers.model prefix openai/ <-> dashscope/",
    )
    ap.add_argument("--apply", action="store_true",
                    help="Actually perform UPDATE; without it dry-run only")
    ap.add_argument("--rollback", action="store_true",
                    help="Reverse direction: dashscope/ -> openai/")
    ap.add_argument("--all", action="store_true",
                    help="Migrate ALL enabled vendor=qwen rows (default: only is_active=True row)")
    args = ap.parse_args()

    forward = not args.rollback
    src_prefix = "openai/" if forward else "dashscope/"
    dst_prefix = "dashscope/" if forward else "openai/"

    direction = "FORWARD (openai/ → dashscope/)" if forward else "ROLLBACK (dashscope/ → openai/)"
    scope = "all enabled qwen rows" if args.all else "active row only"
    print(f"=== ai_providers.model prefix migration ===")
    print(f"direction: {direction}")
    print(f"scope    : {scope}")
    print(f"mode     : {'APPLY (will commit)' if args.apply else 'DRY-RUN'}")
    print()

    try:
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys = ON"))

            # ── Pre-state ────────────────────────────────────────────────
            rows = await _list_qwen_rows(conn)
            if not rows:
                print("No vendor=qwen rows found in ai_providers. Nothing to do.")
                return 0

            print(f"--- Current state (vendor=qwen, type=llm) ---")
            for id_, vendor, model, enabled, is_active, _ in [
                (r[0], r[1], r[4], r[5], r[6], None) for r in rows
            ]:
                tag = " (ACTIVE)" if is_active else ""
                en = "" if enabled else " [DISABLED]"
                print(f"  id={id_:>3} {vendor}/{model!r}{tag}{en}")

            _, targets = _classify(rows, src_prefix, args.all)
            print()

            if not targets:
                print(f"No rows match prefix {src_prefix!r} with current scope. Nothing to do.")
                print(f"(If already migrated, this is the idempotent no-op path.)")
                return 0

            # ── Plan ─────────────────────────────────────────────────────
            print(f"--- Plan ---")
            mutations = []
            for tid, old in targets:
                new = dst_prefix + old[len(src_prefix):]
                mutations.append((tid, old, new))
                print(f"  id={tid}: {old!r}  →  {new!r}")

            if not args.apply:
                print()
                print(f"DRY-RUN. Re-run with --apply to commit ({len(mutations)} row(s)).")
                return 2

            # ── Apply ────────────────────────────────────────────────────
            print()
            print(f"--- Applying (single transaction) ---")
            for tid, old, new in mutations:
                res = await conn.execute(text(
                    "UPDATE ai_providers SET model = :new "
                    "WHERE id = :id AND model = :old"
                ), {"new": new, "old": old, "id": tid})
                rc = getattr(res, "rowcount", -1)
                print(f"  UPDATE id={tid}: rowcount={rc}")
                if rc != 1:
                    raise RuntimeError(
                        f"Expected rowcount=1 for id={tid} (model:{old!r}), got {rc}. "
                        f"Row may have been mutated concurrently; aborting transaction."
                    )

            # ── Verify within same transaction ───────────────────────────
            print()
            print(f"--- Verifying (still in transaction; will commit if all match) ---")
            verified = await _verify(conn, [t[0] for t in targets])
            all_match = True
            for tid, _, new in mutations:
                actual = verified.get(tid)
                ok = "✓" if actual == new else "✗ MISMATCH"
                print(f"  id={tid}: model={actual!r} {ok}")
                if actual != new:
                    all_match = False
            if not all_match:
                raise RuntimeError("Post-update verify failed; aborting transaction.")

        print()
        print(f"✓ Committed. {len(mutations)} row(s) migrated.")
        return 0

    except Exception as exc:
        print(f"\n✗ ERROR: {type(exc).__name__}: {exc}")
        print("Transaction rolled back (no rows changed).")
        return 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

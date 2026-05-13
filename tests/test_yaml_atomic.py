"""Tests for backend.utils.yaml_atomic.write_config_atomic.

Run:
    .venv/bin/python tests/test_yaml_atomic.py

Or via pytest:
    .venv/bin/pytest tests/test_yaml_atomic.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from backend.utils.yaml_atomic import write_config_atomic


PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


# ---------------------------------------------------------------------------
# 1. Basic write — round-trip
# ---------------------------------------------------------------------------

async def test_basic_write() -> None:
    print("\n[test_basic_write — write then read returns same data]")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.yaml"
        # Seed the file with some content
        path.write_text("existing_key: original\nshared: keep_me\n", encoding="utf-8")

        def mutate(d: dict) -> None:
            d["new_key"] = "added"
            d["existing_key"] = "updated"

        result = await write_config_atomic(path, mutate)

        check("returns dict", isinstance(result, dict))
        check("result has new_key", result.get("new_key") == "added")
        check("result has updated existing_key", result.get("existing_key") == "updated")
        check("result preserves shared", result.get("shared") == "keep_me")

        # Re-read from disk
        with open(path, encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        check("on-disk matches", on_disk == result)


# ---------------------------------------------------------------------------
# 2. Concurrent writes — no lost updates
# ---------------------------------------------------------------------------

async def test_concurrent_writes() -> None:
    print("\n[test_concurrent_writes — asyncio.gather two mutations, both land]")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.yaml"
        path.write_text("counter: 0\n", encoding="utf-8")

        # Each mutator increments by a different amount + adds its own key.
        # If lock works, final counter = 0 + 1 + 10 = 11 regardless of order.
        async def mutate_a(d: dict) -> None:
            d["counter"] = int(d.get("counter", 0)) + 1
            d["a_added"] = True
            # Force a context switch mid-mutation so lock is actually exercised
            await asyncio.sleep(0.01)

        async def mutate_b(d: dict) -> None:
            d["counter"] = int(d.get("counter", 0)) + 10
            d["b_added"] = True
            await asyncio.sleep(0.01)

        await asyncio.gather(
            write_config_atomic(path, mutate_a),
            write_config_atomic(path, mutate_b),
        )

        with open(path, encoding="utf-8") as f:
            final = yaml.safe_load(f)

        check("counter accumulated correctly", final.get("counter") == 11,
              f"got {final.get('counter')!r}")
        check("both writers' keys present",
              final.get("a_added") is True and final.get("b_added") is True)


# ---------------------------------------------------------------------------
# 3. Mutate raises — original file unchanged + no tmp left behind
# ---------------------------------------------------------------------------

async def test_mutate_failure_rollback() -> None:
    print("\n[test_mutate_failure_rollback — mutate exception leaves file intact]")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.yaml"
        original_text = "stable: yes\nvalue: 42\n"
        path.write_text(original_text, encoding="utf-8")

        class BoomError(RuntimeError):
            pass

        def bad_mutate(d: dict) -> None:
            d["partial"] = "should_not_persist"
            raise BoomError("simulated mutate failure")

        raised = False
        try:
            await write_config_atomic(path, bad_mutate)
        except BoomError:
            raised = True

        check("BoomError propagated", raised)

        with open(path, encoding="utf-8") as f:
            content = f.read()
        check("file content unchanged", content == original_text,
              f"got {content!r}")

        # No dangling tmp.* files next to the target
        siblings = [p.name for p in path.parent.iterdir() if p.name != path.name]
        check("no dangling tmp files", siblings == [],
              f"found {siblings}")


# ---------------------------------------------------------------------------
# 4. No-file initial — starts from empty dict
# ---------------------------------------------------------------------------

async def test_no_file_initial() -> None:
    print("\n[test_no_file_initial — missing file starts from empty dict]")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.yaml"
        check("file does not exist before", not path.exists())

        captured: dict = {}

        def mutate(d: dict) -> None:
            captured["initial"] = dict(d)  # snapshot
            d["created"] = "first_time"
            d["nested"] = {"a": 1, "b": 2}

        result = await write_config_atomic(path, mutate)

        check("mutate received empty dict", captured.get("initial") == {})
        check("file created on disk", path.exists())
        check("created key persisted", result.get("created") == "first_time")

        with open(path, encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        check("nested dict preserved",
              on_disk.get("nested") == {"a": 1, "b": 2})


# ---------------------------------------------------------------------------
# 5. mutate_fn returns new dict instead of in-place
# ---------------------------------------------------------------------------

async def test_mutate_returns_new_dict() -> None:
    print("\n[test_mutate_returns_new_dict — return value replaces contents]")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.yaml"
        path.write_text("old_key: old_value\n", encoding="utf-8")

        def mutate(d: dict) -> dict:
            # Discard old contents entirely
            return {"only_key": "only_value"}

        result = await write_config_atomic(path, mutate)

        check("result is the returned dict", result == {"only_key": "only_value"})

        with open(path, encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        check("on-disk has only the returned dict",
              on_disk == {"only_key": "only_value"},
              f"got {on_disk!r}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> int:
    await test_basic_write()
    await test_concurrent_writes()
    await test_mutate_failure_rollback()
    await test_no_file_initial()
    await test_mutate_returns_new_dict()

    print(f"\n=== summary: {sum(1 for _, ok in results if ok)}/{len(results)} passed ===")
    failed = [name for name, ok in results if not ok]
    if failed:
        for f in failed:
            print(f"  FAIL: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

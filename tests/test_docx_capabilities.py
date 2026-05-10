"""v3.5 chunk 7 — docx 三 capability 单测 + safe_path 防御。

不污染用户真实 ``~/Documents/Skyler/docs/``：每个 test monkeypatch
``_safe_dir`` 指向 tmpdir。
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.capabilities import docx_ops
from backend.utils.safe_path import safe_resolve, ensure_sandbox_dir

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _patch_safe_dir(tmpdir: Path) -> None:
    """让所有 docx capability 调用都落在 tmpdir 而不是真实 ~/Documents/Skyler。"""
    docx_ops._safe_dir = lambda: ensure_sandbox_dir(tmpdir, mode=0o700)  # type: ignore


# ---------------------------------------------------------------------------
# 1. safe_path util
# ---------------------------------------------------------------------------

def test_safe_resolve_basic():
    print("\n[safe_resolve — 合法 stem]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        out = safe_resolve(base, "foo.docx")
        check("resolves under base", out.parent == base.resolve())
        check("name preserved", out.name == "foo.docx")


def test_safe_resolve_traversal_blocked():
    print("\n[safe_resolve — traversal 拒]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        try:
            safe_resolve(base, "../escape.docx")
            check("../path rejected", False, "no exception raised")
        except ValueError:
            check("../path rejected", True)
        try:
            safe_resolve(base, "/etc/passwd")
            check("absolute rejected", False)
        except ValueError:
            check("absolute rejected", True)
        try:
            safe_resolve(base, "sub/file.docx")
            check("subdir rejected (strict)", False)
        except ValueError:
            check("subdir rejected (strict)", True)


def test_safe_resolve_allow_subdirs():
    print("\n[safe_resolve — allow_subdirs=True 允许嵌套但仍拒 ..]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        # 嵌套合法
        out = safe_resolve(base, "sub/file.docx", allow_subdirs=True)
        check("subdir allowed", out.parent.name == "sub")
        # 但 ../ 仍拒
        try:
            safe_resolve(base, "sub/../../escape.docx", allow_subdirs=True)
            check("../ via subdir rejected", False)
        except ValueError:
            check("../ via subdir rejected", True)


# ---------------------------------------------------------------------------
# 2. docx.create / read / append
# ---------------------------------------------------------------------------

async def test_create_basic():
    print("\n[docx.create — 基本流程]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        r = await docx_ops.docx_create(
            filename="report",
            title="Weekly Report",
            paragraphs=["Para 1", "Para 2", "Para 3"],
        )
        check("no error", "error" not in r, f"got {r!r}")
        check("path returned", r.get("path") == "report.docx")
        check("size > 0", r.get("size_bytes", 0) > 0)
        check("file exists", (Path(tmp) / "report.docx").exists())


async def test_create_auto_docx_suffix():
    print("\n[docx.create — 文件名无后缀自动补 .docx]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        r = await docx_ops.docx_create(
            filename="周报_2026年05月",
            title="周报",
            paragraphs=["本周工作"],
        )
        check("auto-appended .docx", r.get("path") == "周报_2026年05月.docx")


async def test_create_wrong_suffix_rejected():
    print("\n[docx.create — 非 .docx 后缀拒]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        r = await docx_ops.docx_create(
            filename="report.txt",
            title="t",
            paragraphs=[],
        )
        check("rejected with invalid_path", r.get("error") == "invalid_path",
              f"got {r!r}")


async def test_create_path_traversal_rejected():
    print("\n[docx.create — traversal 拒]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        for evil in ["../escape.docx", "/etc/passwd.docx", "sub/file.docx"]:
            r = await docx_ops.docx_create(
                filename=evil, title="t", paragraphs=[],
            )
            check(f"rejected: {evil!r}",
                  r.get("error") == "invalid_path",
                  f"got {r!r}")


async def test_create_missing_required():
    print("\n[docx.create — 缺必填]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        r = await docx_ops.docx_create(filename="", title="t")
        check("missing filename", r.get("error") == "missing_filename")
        r = await docx_ops.docx_create(filename="x", title="")
        check("missing title", r.get("error") == "missing_title")


async def test_read_roundtrip():
    print("\n[docx.read — 读回 create 的内容]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        await docx_ops.docx_create(
            filename="x",
            title="Title 1",
            paragraphs=["Hello", "World"],
        )
        r = await docx_ops.docx_read(filename="x")
        check("no error", "error" not in r, f"got {r!r}")
        check("title parsed from heading", r.get("title") == "Title 1")
        check("paragraphs match",
              r.get("paragraphs") == ["Hello", "World"])
        check("word_count = sum(len)", r.get("word_count") == 10)


async def test_read_file_not_found():
    print("\n[docx.read — 文件不存在]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        r = await docx_ops.docx_read(filename="missing")
        check("file_not_found", r.get("error") == "file_not_found")


async def test_read_parse_failed():
    print("\n[docx.read — 伪造 .docx parse_failed]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        # 用真实 path 写非法 docx 内容
        bad = Path(tmp) / "fake.docx"
        bad.write_bytes(b"not a real docx")
        r = await docx_ops.docx_read(filename="fake")
        check("parse_failed", r.get("error") == "parse_failed",
              f"got {r!r}")


async def test_append_basic():
    print("\n[docx.append — 追加段落]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        await docx_ops.docx_create(
            filename="x",
            title="Hi",
            paragraphs=["one"],
        )
        r = await docx_ops.docx_append(
            filename="x",
            paragraphs=["two", "three"],
        )
        check("appended_count = 2", r.get("appended_count") == 2)
        # 验读回
        r2 = await docx_ops.docx_read(filename="x")
        check("paragraphs after append",
              r2.get("paragraphs") == ["one", "two", "three"])


async def test_append_file_not_found():
    print("\n[docx.append — 文件不存在]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        r = await docx_ops.docx_append(filename="missing", paragraphs=["x"])
        check("file_not_found", r.get("error") == "file_not_found")


async def test_append_empty_rejected():
    print("\n[docx.append — 空 paragraphs 拒]")
    with tempfile.TemporaryDirectory() as tmp:
        _patch_safe_dir(Path(tmp))
        await docx_ops.docx_create(filename="x", title="t", paragraphs=[])
        r = await docx_ops.docx_append(filename="x", paragraphs=[])
        check("empty_paragraphs", r.get("error") == "empty_paragraphs")


# ---------------------------------------------------------------------------
# 3. capability registration 检查
# ---------------------------------------------------------------------------

def test_capabilities_registered():
    print("\n[chunk 7 — 三 capability 注册到 ToolRegistry]")
    from backend.tools.registry import ToolRegistry
    names = {s["function"]["name"] for s in ToolRegistry.list_schemas()
             if "function" in s}
    check("docx.create registered", "docx.create" in names)
    check("docx.read registered", "docx.read" in names)
    check("docx.append registered", "docx.append" in names)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def amain():
    await test_create_basic()
    await test_create_auto_docx_suffix()
    await test_create_wrong_suffix_rejected()
    await test_create_path_traversal_rejected()
    await test_create_missing_required()
    await test_read_roundtrip()
    await test_read_file_not_found()
    await test_read_parse_failed()
    await test_append_basic()
    await test_append_file_not_found()
    await test_append_empty_rejected()


def main():
    test_safe_resolve_basic()
    test_safe_resolve_traversal_blocked()
    test_safe_resolve_allow_subdirs()
    asyncio.run(amain())
    test_capabilities_registered()

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

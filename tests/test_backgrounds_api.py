"""v3.5 chunk 5a — GET /api/backgrounds + scanner unit tests。

不依赖真实 ``frontend/public/backgrounds/`` 目录（用户随时增减素材）；
test 自己在 tmpdir 造一个目录树，monkeypatch _BACKGROUNDS_DIR /
_PUBLIC_ROOT 后扫描。

覆盖：
  1. 空目录 → items=[]
  2. 后缀白名单：image / video 分类正确；README.md / .gitkeep / 用户暂存
     源文件被忽略
  3. 子目录一层深递归：name 用 ``<subdir>/<stem>``
  4. symlink 兼容：``.absolute()`` 不解析，URL 仍指向 repo path 命名空间
  5. /api/backgrounds 端到端（FastAPI TestClient）
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import backgrounds_scanner as scanner_mod

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _setup_fake_dirs(tmp_root: Path) -> tuple[Path, Path]:
    """构造 frontend/public/backgrounds/ 假目录，返回 (public_root, bg_dir)。"""
    public_root = tmp_root / "frontend" / "public"
    bg_dir = public_root / "backgrounds"
    bg_dir.mkdir(parents=True)
    return public_root, bg_dir


def _patch_scanner_paths(public_root: Path, bg_dir: Path):
    scanner_mod._PUBLIC_ROOT = public_root
    scanner_mod._BACKGROUNDS_DIR = bg_dir


# ---------------------------------------------------------------------------
# 1. 空目录
# ---------------------------------------------------------------------------

def test_empty_dir():
    print("\n[scanner — empty dir → items=[]]")
    with tempfile.TemporaryDirectory() as tmp:
        public_root, bg_dir = _setup_fake_dirs(Path(tmp))
        _patch_scanner_paths(public_root, bg_dir)
        r = scanner_mod.scan_backgrounds()
        check("scan_dir is repo-relative",
              r["scan_dir"] == "frontend/public/backgrounds")
        check("items empty", r["items"] == [])


# ---------------------------------------------------------------------------
# 2. 后缀白名单
# ---------------------------------------------------------------------------

def test_extension_whitelist():
    print("\n[scanner — image / video classified；其他后缀忽略]")
    with tempfile.TemporaryDirectory() as tmp:
        public_root, bg_dir = _setup_fake_dirs(Path(tmp))
        # 各种文件
        (bg_dir / "tokyo_rain.mp4").write_bytes(b"fake mp4 ")
        (bg_dir / "shrine.JPG").write_bytes(b"fake jpg ")   # 大写后缀也认
        (bg_dir / "neon.png").write_bytes(b"fake png ")
        (bg_dir / "fog.webp").write_bytes(b"fake webp")
        (bg_dir / "intro.webm").write_bytes(b"fake webm")
        (bg_dir / "README.md").write_text("docs")           # 忽略
        (bg_dir / ".gitkeep").write_text("")                # 忽略
        (bg_dir / "source.psd").write_bytes(b"")            # 忽略

        _patch_scanner_paths(public_root, bg_dir)
        r = scanner_mod.scan_backgrounds()

        names = {it["name"] for it in r["items"]}
        types = {it["name"]: it["type"] for it in r["items"]}
        check("count 5 (jpg/png/webp/mp4/webm)", len(r["items"]) == 5,
              f"got {len(r['items'])}: {names}")
        check("tokyo_rain → video", types.get("tokyo_rain") == "video")
        check("shrine (uppercase JPG) → image", types.get("shrine") == "image")
        check("neon → image", types.get("neon") == "image")
        check("fog → image", types.get("fog") == "image")
        check("intro → video", types.get("intro") == "video")
        check("README excluded", "README" not in names)
        check("source.psd excluded", "source" not in names)

        # path 是 /-prefixed URL
        for it in r["items"]:
            if it["name"] == "tokyo_rain":
                check("path is /-prefixed URL",
                      it["path"] == "/backgrounds/tokyo_rain.mp4",
                      f"got {it['path']!r}")
                check("size > 0", it["size"] > 0)


# ---------------------------------------------------------------------------
# 3. 子目录递归（一层深）
# ---------------------------------------------------------------------------

def test_subdir_one_level():
    print("\n[scanner — 一层子目录递归]")
    with tempfile.TemporaryDirectory() as tmp:
        public_root, bg_dir = _setup_fake_dirs(Path(tmp))
        (bg_dir / "tokyo").mkdir()
        (bg_dir / "tokyo" / "rain.mp4").write_bytes(b"x")
        (bg_dir / "tokyo" / "neon.jpg").write_bytes(b"x")
        # 二层子目录不扫
        (bg_dir / "tokyo" / "deeper").mkdir()
        (bg_dir / "tokyo" / "deeper" / "hidden.mp4").write_bytes(b"x")

        _patch_scanner_paths(public_root, bg_dir)
        r = scanner_mod.scan_backgrounds()
        names = {it["name"] for it in r["items"]}
        check("subdir entries prefixed",
              "tokyo/rain" in names and "tokyo/neon" in names,
              f"got {names}")
        check("二层目录 hidden 不进列表",
              "hidden" not in names and "tokyo/deeper/hidden" not in names,
              f"got {names}")
        # path 验证
        for it in r["items"]:
            if it["name"] == "tokyo/rain":
                check("subdir path correct",
                      it["path"] == "/backgrounds/tokyo/rain.mp4",
                      f"got {it['path']!r}")


# ---------------------------------------------------------------------------
# 4. symlink 兼容
# ---------------------------------------------------------------------------

def test_symlink_compat():
    print("\n[scanner — symlink 用 .absolute() 不解析]")
    with tempfile.TemporaryDirectory() as tmp:
        public_root, bg_dir = _setup_fake_dirs(Path(tmp))
        # 在 tmp 外（视作"外部 IP 资产"）放一个文件
        external_dir = Path(tmp) / "external_assets"
        external_dir.mkdir()
        real_file = external_dir / "private.mp4"
        real_file.write_bytes(b"external content")
        # bg_dir/private.mp4 → 外部链接
        try:
            (bg_dir / "private.mp4").symlink_to(real_file)
        except (NotImplementedError, OSError):
            print("  (skipping: symlink not supported on this filesystem)")
            return

        _patch_scanner_paths(public_root, bg_dir)
        r = scanner_mod.scan_backgrounds()
        # symlink 应该被扫到，且 path 在 repo path 命名空间内（不是解析后的真实路径）
        names = {it["name"] for it in r["items"]}
        check("symlink scanned", "private" in names, f"got {names}")
        for it in r["items"]:
            if it["name"] == "private":
                check("symlink path stays in repo namespace",
                      it["path"] == "/backgrounds/private.mp4",
                      f"got {it['path']!r}")


# ---------------------------------------------------------------------------
# 5. API endpoint
# ---------------------------------------------------------------------------

def test_api_endpoint():
    print("\n[GET /api/backgrounds — end-to-end]")
    with tempfile.TemporaryDirectory() as tmp:
        public_root, bg_dir = _setup_fake_dirs(Path(tmp))
        (bg_dir / "morning.jpg").write_bytes(b"x")
        _patch_scanner_paths(public_root, bg_dir)

        from backend.routes.backgrounds_api import router
        app = FastAPI()
        app.include_router(router, prefix="/api")
        client = TestClient(app)
        r = client.get("/api/backgrounds")
        check("status 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        check("scan_dir field present",
              data.get("scan_dir") == "frontend/public/backgrounds")
        check("items array",
              isinstance(data.get("items"), list) and len(data["items"]) == 1)
        check("item shape",
              data["items"][0]["name"] == "morning"
              and data["items"][0]["type"] == "image"
              and data["items"][0]["path"] == "/backgrounds/morning.jpg")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    # Save originals so tests are isolated even if user runs all at once
    orig_public  = scanner_mod._PUBLIC_ROOT
    orig_bg_dir  = scanner_mod._BACKGROUNDS_DIR
    try:
        test_empty_dir()
        test_extension_whitelist()
        test_subdir_one_level()
        test_symlink_compat()
        test_api_endpoint()
    finally:
        scanner_mod._PUBLIC_ROOT = orig_public
        scanner_mod._BACKGROUNDS_DIR = orig_bg_dir

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

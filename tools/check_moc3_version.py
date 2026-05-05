"""扫描目录里所有 .moc3 文件，输出每个的版本号并判定 pixi-live2d-display 是否支持。

背景
----
pixi-live2d-display 及其所有 fork（advanced / lipsyncpatch / mulmotion）只
支持 Cubism 4 Core，不支持 Cubism 5（GitHub issue #118 自 2023-10 至今未修复）。
Skyler 在 Live2D 渲染层锁死在 ver ≤ 4 的 .moc3 文件，v3-E2 选购 / 接收模型
时必须先用本脚本验证。

moc3 二进制头（小端）
- bytes [0..4)  ASCII magic "MOC3"
- byte  [4]     uint8 version
- byte  [5]     uint8 endianness flag（big_endian = 0x01；不影响版本判定）
- bytes [6..8)  reserved
- bytes [8..12) uint32 file size
- ...           parameter / model 数据，本脚本不解析

version 字节对照（社区共识，对应 Cubism Editor 导出选项）
    1 → Cubism SDK 3.0
    2 → Cubism SDK 3.3
    3 → Cubism SDK 4.0
    4 → Cubism SDK 4.2  ← pixi-live2d-display 支持上限
    5 → Cubism SDK 5.0  ← 不支持
    6+ → 未来版本

Cubism 5 编辑器制作的模型可以"以 4.x 兼容选项重新导出"得到 ver ≤ 4 的
.moc3，本脚本只检查最终二进制版本，不关心源工程。

用法
----
    python -m tools.check_moc3_version <DIR_OR_FILE> [<DIR_OR_FILE> ...]

退出码
------
    0  全部 .moc3 都 ver ≤ 4
    1  存在 ver ≥ 5 的 .moc3 / 存在 magic 不匹配的 .moc3 / Cubism 2 .moc
    2  没找到任何 .moc3 / .moc（路径错 / 空目录）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

MOC3_MAGIC = b"MOC3"
PIXI_MAX_SUPPORTED = 4

# version → 人类可读 SDK 标签
SDK_LABEL = {
    1: "Cubism SDK 3.0",
    2: "Cubism SDK 3.3",
    3: "Cubism SDK 4.0",
    4: "Cubism SDK 4.2",
    5: "Cubism SDK 5.0",
}


class Moc3Info(NamedTuple):
    path: Path
    version: Optional[int]   # None 表示文件读不到 / magic 不对
    error: Optional[str]


def parse_moc3_version(path: Path) -> Moc3Info:
    """读取头 5 字节，校验 magic 并返回 version。"""
    try:
        with path.open("rb") as f:
            head = f.read(5)
    except OSError as exc:
        return Moc3Info(path, None, f"read error: {exc}")
    if len(head) < 5:
        return Moc3Info(path, None, f"file too short ({len(head)} bytes)")
    if head[:4] != MOC3_MAGIC:
        return Moc3Info(path, None, f"bad magic: {head[:4]!r}")
    return Moc3Info(path, head[4], None)


# 同时收集 .moc（Cubism 2）—— 让旧资产能在 magic 校验阶段被显式 FAIL，
# 而不是变成"路径下没找到 .moc3"这种容易被误读为"目录拼错了"的状态。
_MOC_SUFFIXES = (".moc3", ".moc")


def discover_moc3(targets: Iterable[str]) -> list[Path]:
    """传入文件 / 目录混合列表，递归收集所有 .moc3 / .moc 路径。

    .moc（Cubism 2）会被一并收集；parse_moc3_version 在 magic 校验阶段
    会判 "bad magic"（Cubism 2 的 .moc 头不是 ASCII MOC3）—— 走 FAIL 路径
    而不是"未发现任何文件"。
    """
    seen: set[Path] = set()
    for t in targets:
        p = Path(t).expanduser()
        if not p.exists():
            print(f"[WARN] path does not exist: {p}", file=sys.stderr)
            continue
        if p.is_file():
            if p.suffix.lower() in _MOC_SUFFIXES:
                seen.add(p.resolve())
        else:
            for suffix in _MOC_SUFFIXES:
                for f in p.rglob(f"*{suffix}"):
                    seen.add(f.resolve())
    return sorted(seen)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    files = discover_moc3(argv)
    if not files:
        print("No .moc3 files found in given paths.")
        return 2

    bad = 0
    for f in files:
        info = parse_moc3_version(f)
        if info.error:
            print(f"  [ERR] {f}  {info.error}")
            bad += 1
            continue
        v = info.version
        label = SDK_LABEL.get(v, f"unknown SDK (v={v})")
        verdict = "OK" if v <= PIXI_MAX_SUPPORTED else "TOO NEW"
        print(f"  [{verdict}] version={v} ({label})  {f}")
        if v > PIXI_MAX_SUPPORTED:
            bad += 1

    print()
    print(f"Total: {len(files)} file(s); {bad} unsupported by pixi-live2d-display.")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

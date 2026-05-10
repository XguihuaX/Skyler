"""Path traversal-safe sandbox helpers (v3.5 chunk 7 起共享)。

为 docx / future skill capability 提供统一的"用户传入路径必须在沙箱内"
校验。原 ``backend/integrations/google_calendar.py`` 等模块各自 ad-hoc 写
路径，本模块把模式集中：

* ``ensure_sandbox_dir(base)``——首次启动时创建沙箱目录，``mode=0o700``
  在 macOS / Linux 上限制其他用户访问（Windows 上 chmod 静默无效）
* ``safe_resolve(base, user_path)``——把用户输入的相对路径（filename）
  resolve 后强制要求落在 ``base`` 内；越界 → ``ValueError``

设计准则：
  - 不允许绝对路径 / 含 ``..`` / 含路径分隔符的文件名（chunk 7 capability
    设计文件名只是 stem，不允许子目录）。本模块 ``safe_resolve`` 同时支
    持"只允许相对 stem"和"允许沙箱内任意嵌套"两种 strict 度——通过
    ``allow_subdirs`` 参数区分。
  - Symlink discipline：用 ``.resolve()`` 解析后比较。沙箱内若有 symlink
    指向外部文件，会被识破并拒绝。与 live2d/backgrounds scanner 的
    ``.absolute()`` 策略相反——那俩是 *列出* 资产（信任 dev 加的 symlink），
    本模块是 *接收用户输入*（必须防御）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Final


# Windows path separator 也防一手，跨平台一致
_PATH_SEPS: Final[tuple[str, ...]] = ("/", "\\")


def ensure_sandbox_dir(base: Path, *, mode: int = 0o700) -> Path:
    """Ensure ``base`` exists with restrictive permissions; return resolved path.

    Idempotent: ``parents=True, exist_ok=True``. ``mode`` only takes effect on
    POSIX (Windows ignores chmod from Python, falls back to umask)。
    """
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, mode)
    except (OSError, NotImplementedError):
        # Windows / read-only FS → ignore
        pass
    return base.resolve()


def safe_resolve(
    base: Path,
    user_path: str,
    *,
    allow_subdirs: bool = False,
) -> Path:
    """Validate ``user_path`` lands inside ``base`` and return resolved path.

    Args:
        base:          Sandbox root（必须已存在；调用方负责 ``ensure_sandbox_dir``）
        user_path:     用户/LLM 提供的字符串（filename 或相对路径）
        allow_subdirs: ``False`` —— 仅允许 stem（``"weekly_report.docx"``），
                       不允许任何 ``/`` 或 ``\\``；``True`` —— 允许沙箱内嵌套
                       （``"reports/2026-Q2/weekly.docx"``），仍拒绝 ``..``
                       逃逸。

    Returns:
        Resolved absolute path inside ``base``.

    Raises:
        ValueError: 路径越界 / 含非法字符。错误消息不暴露 ``base`` 绝对路径
                    避免泄露 workstation 布局。
    """
    if not user_path or not user_path.strip():
        raise ValueError("empty path")
    s = user_path.strip()

    # 绝对路径直接拒
    if os.path.isabs(s):
        raise ValueError("absolute paths not allowed")

    if not allow_subdirs:
        # 严格模式：只允许 stem
        for sep in _PATH_SEPS:
            if sep in s:
                raise ValueError("path separators not allowed in filename")
        if s in (".", "..") or s.startswith("."):
            raise ValueError("dot files not allowed")

    base_resolved = base.resolve()
    candidate = (base_resolved / s).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        # ``../etc/passwd`` 等会让 resolve 跳出 base
        raise ValueError("path escapes sandbox")
    return candidate

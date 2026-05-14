"""bugfix-3.1: 本地对称加密 helper, 给 ``ai_vendor_credentials`` 用。

设计:
  * Fernet (cryptography 库) —— AES-128-CBC + HMAC-SHA256, URL-safe base64
  * Master key 一次性生成 ``Fernet.generate_key()`` 写到 ``~/.skyler/.crypto_key``
    (chmod 0600), 进程启动 lazy 加载并 cache
  * 兼容 mcp_credentials 走的明文 V1 路径 —— 不动它, 只给 AI vendor 用
    fernet。后续若要把 mcp 升级, 共用本 helper 即可

不做的事:
  * 不接 OS keyring (macOS Keychain 等), ROADMAP backlog 已有
  * 不做密钥轮转 / 多 master / KDF —— 单用户 V1 spec
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_CACHED: Optional[Fernet] = None


def _key_path() -> Path:
    """``~/.skyler/.crypto_key`` —— SQLite 同目录, 系统级用户隔离。"""
    return Path.home() / ".skyler" / ".crypto_key"


def _load_or_create_key() -> bytes:
    """First-run 创建 + 后续读取。chmod 0600 limit 给当前用户。"""
    path = _key_path()
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.warning("[crypto] chmod 0600 failed on %s", path)
    logger.info("[crypto] generated new master key at %s", path)
    return key


def get_fernet() -> Fernet:
    global _CACHED
    if _CACHED is None:
        _CACHED = Fernet(_load_or_create_key())
    return _CACHED


def encrypt(plaintext: str) -> str:
    """UTF-8 str → fernet token (URL-safe base64 str)。空串原样返回。"""
    if not plaintext:
        return ""
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Fernet token → UTF-8 str。空串原样返回。
    解密失败抛 ``InvalidToken``(密钥换了 / 数据损坏 / 明文混入)——caller
    决定要不要兜底成空 / 提示用户重配。"""
    if not ciphertext:
        return ""
    return get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def try_decrypt(ciphertext: str) -> Optional[str]:
    """安全版 decrypt: 失败返回 None 而不是抛, 用于不关键路径。"""
    if not ciphertext:
        return None
    try:
        return decrypt(ciphertext)
    except InvalidToken:
        logger.warning("[crypto] decrypt failed (InvalidToken)")
        return None

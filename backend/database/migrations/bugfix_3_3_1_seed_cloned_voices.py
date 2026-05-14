"""Bugfix-3.3.1 — 灌入用户预复刻的 3 个 CosyVoice voice_id 到 characters 表。

用户已在 DashScope 控制台用音色复刻 (https://help.aliyun.com/zh/model-studio/
voice-cloning) 注册了 3 个 ``cosyvoice-v3.5-plus-bailian-<32hex>`` voice_id,
要绑到对应角色 (id=2 八重神子 / id=3 荧 / id=5 神里绫华)。

幂等策略
--------
1. 角色不存在 → 跳过 (用户可能删了角色)
2. ``voice_model.voice`` 已是 ``cosyvoice-v3.5-plus-bailian-*`` → 跳过
   (用户之前已复刻或手改过, 不覆盖)
3. ``voice_model`` 为 NULL / 空 / 系统音色 (longxxx) → 写入复刻 voice_id

写入的 ``voice_model`` JSON 结构:
{
  "provider": "cosyvoice",
  "model": "cosyvoice-v3.5-plus",
  "voice": "<voice_id>",
  "instruct_supported": true,
  "ssml_supported": true
}

backend/tts/voice_config.py parse_voice_config 当前只读 provider / voice /
instruct_supported 三个字段; ``model`` 和 ``ssml_supported`` 是面向未来 TTS
dispatcher (v4.1+) 的占位, 当前 CosyVoiceTTS 用 yaml::tts.cosyvoice.model
(``cosyvoice-v3-flash``) 而非这里的 ``cosyvoice-v3.5-plus``。这个不一致是
**已知的**, 留给后续 stage 修 — 当前 voice id 走 v3.5-plus 但 SDK 调用走
v3-flash 也能命中复刻 voice (DashScope voice_id 跨 model 版本通用)。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


# (character_id, voice_id, expected_name) — name 仅用于 log,不严格匹配
_CLONED_VOICES: list[tuple[int, str, str]] = [
    (2, "cosyvoice-v3.5-plus-bailian-a61ea44f8a9648b3920b7ef98280d226", "八重神子"),
    (3, "cosyvoice-v3.5-plus-bailian-ec2676aa187a44a2b448a37a239b29af", "荧"),
    (5, "cosyvoice-v3.5-plus-bailian-7c617acd71b54130ac14ea7158718916", "神里绫华"),
]

_CLONED_VOICE_PREFIX = "cosyvoice-v3.5-plus-bailian-"


def _build_voice_model_json(voice_id: str) -> str:
    """构造 voice_model JSON 字符串。ensure_ascii=False 让 SQLite 存可读形态。"""
    payload = {
        "provider": "cosyvoice",
        "model": "cosyvoice-v3.5-plus",
        "voice": voice_id,
        "instruct_supported": True,
        "ssml_supported": True,
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_current_voice(vm_str: Optional[str]) -> Optional[str]:
    """返回 voice_model JSON 中的 voice 字段; None / 不合法 → None。"""
    if not vm_str:
        return None
    try:
        data = json.loads(vm_str)
        if isinstance(data, dict):
            v = data.get("voice")
            return v if isinstance(v, str) else None
    except json.JSONDecodeError:
        return None
    return None


async def run_migration() -> None:
    """Bugfix-3.3.1 主迁移。幂等: 已是 cloned voice 不动, 其他都覆盖。"""
    async with engine.begin() as conn:
        # characters 表 schema 不需要 PRAGMA FK; 这里跟其他 migration 保持一致
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        seeded = 0
        skipped_already_cloned = 0
        skipped_missing = 0

        for char_id, voice_id, expected_name in _CLONED_VOICES:
            row = (await conn.execute(text(
                "SELECT name, voice_model FROM characters WHERE id = :id"
            ), {"id": char_id})).first()

            if row is None:
                logger.warning(
                    "[bugfix-3.3.1] char_id=%s (%r) 不存在, 跳过",
                    char_id, expected_name,
                )
                skipped_missing += 1
                continue

            actual_name, current_vm = row[0], row[1]
            current_voice = _parse_current_voice(current_vm)

            if current_voice and current_voice.startswith(_CLONED_VOICE_PREFIX):
                logger.info(
                    "[bugfix-3.3.1] char_id=%s (%r) 已有 cloned voice=%s, 跳过",
                    char_id, actual_name, current_voice,
                )
                skipped_already_cloned += 1
                continue

            new_vm = _build_voice_model_json(voice_id)
            await conn.execute(text(
                "UPDATE characters SET voice_model = :vm WHERE id = :id"
            ), {"vm": new_vm, "id": char_id})
            logger.info(
                "[bugfix-3.3.1] char_id=%s (%r) → voice=%s "
                "(expected name=%r, prev voice=%s)",
                char_id, actual_name, voice_id, expected_name,
                current_voice or "<empty>",
            )
            seeded += 1

        logger.info(
            "[bugfix-3.3.1] done: seeded=%d skipped_already_cloned=%d "
            "skipped_missing=%d",
            seeded, skipped_already_cloned, skipped_missing,
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())

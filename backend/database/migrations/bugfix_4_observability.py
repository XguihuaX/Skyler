"""Bugfix-4 — observability: tts_call_log 表 + indexes。

埋点表 — 每次 CosyVoice synthesize 调用一行 (成功 + 失败都记)。前端用作:
- TTS 今日 / 本月用量 (按 source 聚合)
- 异常 call 检测 (input_chars > 500 可能是 thinking/state tag 漏)
- recent_calls 抓样查看 input_preview 诊断

Schema:
- timestamp:        默认 CURRENT_TIMESTAMP, 主要 index
- source:           'chat' | 'proactive' | 'activity_smart' | 'preview' | 'unknown'
- character_id:     nullable, INSERT 时若 context 已设则带上
- voice:            实际 voice_id (eg cosyvoice-v3.5-plus-bailian-... / longanhuan)
- model:            cosyvoice-v3-flash / cosyvoice-v3.5-plus 等
- input_chars:      原始 text 字符数 (剥 tag 后送 SDK 的 cleaned)
- input_preview:    前 200 char 抓样, 防隐私 + 大小可控
- cost_estimate:    估算 ¥ (CosyVoice 单价 ~¥0.0007/char,各模型不同,本字段先存)
- success:          1/0
- error_message:    失败时 SDK 错误

Indexes 给前端 GET /api/observability/tts/usage 用 — timestamp WHERE filter,
source 按列聚合。无 character_id 索引 (用量按 source 聚合,不按 char)。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tts_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT NOT NULL,
                character_id INTEGER,
                voice TEXT,
                model TEXT,
                input_chars INTEGER NOT NULL,
                input_preview TEXT,
                cost_estimate REAL,
                success INTEGER NOT NULL DEFAULT 1,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_tts_log_timestamp "
            "ON tts_call_log(timestamp)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_tts_log_source "
            "ON tts_call_log(source)"
        ))
    logger.info("[bugfix-4] tts_call_log table + indexes ensured")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())

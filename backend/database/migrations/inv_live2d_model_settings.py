"""2026-06-16 INV · live2d_model_settings 表(per-model 设置容器)。

挂 Live2D 模型(model_key = scanner slug · 等于 frontend/public/live2d/<slug>/
目录名 · 也等于 character.live2d_model 字段),不挂 character.id —— 模型原生
比例决定怎么裁,共用 slug 的角色共享 framing。

容器 JSON shape(本期只写 framing 一个 section · 其它键透传不动):

    {
      "framing": { "scale": 1.0, "offsetX": 0, "offsetY": 0 }
      // 留位:param_map / director / future · merge 不替换
    }

幂等:CREATE TABLE IF NOT EXISTS;重复执行 no-op。

routes:
  GET   /api/live2d/models/{model_key}/settings
  PATCH /api/live2d/models/{model_key}/settings   merge 语义({**existing, framing: new})
"""
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS live2d_model_settings ("
            "  model_key     TEXT PRIMARY KEY,"
            "  settings_json TEXT NOT NULL,"
            "  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        logger.info(
            "INV-live2d-framing: live2d_model_settings 表已就绪(model_key PK)"
        )

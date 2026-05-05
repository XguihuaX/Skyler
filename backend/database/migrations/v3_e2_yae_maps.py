"""V3-E2 chunk 6：把 character id=2（八重神子）接到 BCSZ1.1 模型 + 写入
per-character emotion / motion / hit-area maps。

幂等：单字段独立判断 —— 字段为 NULL / 空才写默认 mapping，已有值（用户
手改）保留不动。``live2d_model`` 同样原则。

字段语义
--------
``live2d_model='yae'``
    映射到 ``frontend/public/live2d/yae/``。资产由用户用 ``cp -r`` /
    ``ln -s`` 从 BCSZ1.1 源放进去（详见报告"用户测试指南"）。该目录已被
    .gitignore 排除（IP 风险）。

``motion_map_json``
    Skyler 17 个 logical motion 名 → BCSZ1.1 实际 motion group + index。
    包括：
    - ``"Tap"`` —— 点击 Live2DCanvas 的即时反馈（v3-E1 写死 'Tap' group +
      random[0,1]，本表覆盖后改走 motion_map['Tap']）
    - 16 个 LLM 中文动作词（v3-E1 step 6 _build_motion_instruction 列出的
      "放松/随意/慵懒/没事/害羞/不好意思/腼腆/小动作/加油/兴奋/应援/欢呼/
       雀跃/撒娇/俏皮/调皮"），按八重各 motion group 的语义就近 best-effort
      分配。用户可以后期手改 motion_map_json 微调。

``hit_area_map_json``
    BCSZ1.1.model3.json HitAreas Name → 对应 motion group。当前 v3-E2
    Live2DCanvas 还没启用 hit-test 路由（autoHitTest=false），先把契约写
    入 DB，未来接通 click → hitTest → motion 时按本表查表。

``emotion_map_json``
    ``{}`` —— 八重资产没有 .exp3.json，runtime.setExpression 调用会被
    SDK silent-no-op。emotion 数据流仍在跑（后端 push → store → useEffect），
    只是视觉绑定空 map → 不调 SDK，行为同 Hiyori。v3-E3 接入有 expression
    的模型时这里再填。

资产来源
--------
``/Users/liujunhong/Desktop/2dlive/CubismSdkForWeb-5-r.4/Samples/TypeScript/
Demo/public/Resources/BCSZ1.1/``，CC 不复制 / 不入库；用户跑 ``cp -r`` /
``ln -s`` 自己接入。BCSZ1.1.model3.json 实测：moc3 ver=3（pixi 兼容），
10 个 motion（Tap无聊/归零/尾巴/早上好/中午好/晚上好/头饰/不变 + Start +
Shake），8 个 HitAreas，0 个 expression（无 FileReferences.Expressions
字段）。
"""
import asyncio
import json
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mapping 设计 —— 详见模块顶 docstring
# ---------------------------------------------------------------------------

# 八重的"点击立即反馈"动作：用 Start group（初见，带音频，最自然）
# v3-E1 默认 Hiyori 是 'Tap' group + random[0,1]，本 map 接管后走 Start[0]。
# Live2DCanvas handleTouch 改造：先查 motion_map['Tap']，命中走表；miss
# 才回退 v3-E1 的 'Tap' group 写死路径（Hiyori 无 'Tap' key → 走回退）。
_YAE_MOTION_MAP = {
    "Tap":        {"group": "Start",      "index": 0},

    # LLM 中文 motion 词（与 chat.py _build_motion_instruction 对齐）
    "放松":       {"group": "Tap无聊",    "index": 0},
    "随意":       {"group": "Tap无聊",    "index": 0},
    "慵懒":       {"group": "Tap无聊",    "index": 0},
    "没事":       {"group": "Tap归零",    "index": 0},

    "害羞":       {"group": "Tap尾巴",    "index": 0},
    "不好意思":   {"group": "Tap尾巴",    "index": 0},
    "腼腆":       {"group": "Tap尾巴",    "index": 0},
    "小动作":     {"group": "Tap尾巴",    "index": 0},

    "加油":       {"group": "Tap早上好",  "index": 0},
    "兴奋":       {"group": "Start",      "index": 0},
    "应援":       {"group": "Tap早上好",  "index": 0},
    "欢呼":       {"group": "Start",      "index": 0},
    "雀跃":       {"group": "Tap早上好",  "index": 0},

    "撒娇":       {"group": "Tap头饰",    "index": 0},
    "俏皮":       {"group": "Tap头饰",    "index": 0},
    "调皮":       {"group": "Tap头饰",    "index": 0},
}

_YAE_HIT_AREA_MAP = {
    "无聊":   "Tap无聊",
    "归零":   "Tap归零",
    "尾巴":   "Tap尾巴",
    "早上好": "Tap早上好",
    "中午好": "Tap中午好",
    "晚上好": "Tap晚上好",
    "头饰":   "Tap头饰",
    "不变":   "Tap不变",
}

# 八重无 .exp3.json → 空 map。Live2DCanvas emotion useEffect 查空表 →
# 不调 setExpression，行为跟 Hiyori 一致（数据流跑，视觉无变化）。
_YAE_EMOTION_MAP: dict[str, str] = {}


# 字符串化（DB TEXT 字段存 JSON 字符串）。ensure_ascii=False 让中文键直存，
# 调试 SELECT 出来人眼可读。
_YAE_MOTION_JSON   = json.dumps(_YAE_MOTION_MAP,   ensure_ascii=False)
_YAE_HIT_AREA_JSON = json.dumps(_YAE_HIT_AREA_MAP, ensure_ascii=False)
_YAE_EMOTION_JSON  = json.dumps(_YAE_EMOTION_MAP,  ensure_ascii=False)


_YAE_CHARACTER_ID = 2


async def run_migration() -> None:
    """V3-E2 八重 maps 主迁移函数。幂等，可重复执行。"""
    async with engine.begin() as conn:
        row = (await conn.execute(
            text(
                "SELECT id, name, live2d_model, "
                "emotion_map_json, motion_map_json, hit_area_map_json "
                "FROM characters WHERE id = :id"
            ),
            {"id": _YAE_CHARACTER_ID},
        )).fetchone()

        if row is None:
            logger.warning(
                "V3-E2 yae: character id=%d not found, skipping migration. "
                "Create the 八重神子 character via UI first.",
                _YAE_CHARACTER_ID,
            )
            return

        _, name, live2d_model, emotion_json, motion_json, hit_area_json = row
        logger.info(
            "V3-E2 yae: found character id=%d name=%s, evaluating fields...",
            _YAE_CHARACTER_ID, name,
        )

        # live2d_model：仅在 NULL / 空 / "Hiyori"（之前误绑的占位）时改写到 'yae'。
        # 用户已手设其他值（如 'yae-v2' 自定义资产）则保留。
        if not live2d_model or live2d_model.strip().lower() in ("", "hiyori"):
            await conn.execute(
                text(
                    "UPDATE characters SET live2d_model = :v WHERE id = :id"
                ),
                {"v": "yae", "id": _YAE_CHARACTER_ID},
            )
            logger.info(
                "V3-E2 yae: live2d_model %r -> 'yae'", live2d_model,
            )
        else:
            logger.info(
                "V3-E2 yae: live2d_model already %r, keeping",
                live2d_model,
            )

        # 三个 map 字段独立判断：NULL / 空才写默认；非空保留（用户手改）
        if not motion_json or motion_json.strip() in ("", "{}"):
            await conn.execute(
                text(
                    "UPDATE characters SET motion_map_json = :v WHERE id = :id"
                ),
                {"v": _YAE_MOTION_JSON, "id": _YAE_CHARACTER_ID},
            )
            logger.info("V3-E2 yae: motion_map_json written (%d entries)",
                        len(_YAE_MOTION_MAP))
        else:
            logger.info("V3-E2 yae: motion_map_json already populated, keeping")

        if not hit_area_json or hit_area_json.strip() in ("", "{}"):
            await conn.execute(
                text(
                    "UPDATE characters SET hit_area_map_json = :v WHERE id = :id"
                ),
                {"v": _YAE_HIT_AREA_JSON, "id": _YAE_CHARACTER_ID},
            )
            logger.info("V3-E2 yae: hit_area_map_json written (%d entries)",
                        len(_YAE_HIT_AREA_MAP))
        else:
            logger.info("V3-E2 yae: hit_area_map_json already populated, keeping")

        # emotion_map_json：八重无 expression，本就该是 ``{}``。仅在 NULL 时
        # 写空 dict（区分"没设过"和"故意置空"）；已经是 ``{}`` 跳过；用户写
        # 了非空值（v3-E3 接 8 重 mod 时手填）保留。
        if emotion_json is None:
            await conn.execute(
                text(
                    "UPDATE characters SET emotion_map_json = :v WHERE id = :id"
                ),
                {"v": _YAE_EMOTION_JSON, "id": _YAE_CHARACTER_ID},
            )
            logger.info("V3-E2 yae: emotion_map_json initialized to '{}' "
                        "(BCSZ1.1 has no .exp3.json)")
        else:
            logger.info("V3-E2 yae: emotion_map_json already set (%r), keeping",
                        emotion_json[:40] if emotion_json else emotion_json)

    logger.info("V3-E2 yae migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())

"""V3-E2 chunk 7：把 Momo (id=1) persona 还原成 ChatAgent 原文。

背景：v3-E1 全程 Hiyori 跟 Momo 绑定，但用户给 Momo 写了八重神子的 persona
（占位用，因为只有 Momo 绑了 Live2D），导致 system prompt 一直用错人格。
现在 v3-E2 chunk 6 把八重神子 (id=2) 接到 BCSZ1.1，可以把 Momo 还原。

幂等检测策略
------------
Momo 的 ChatAgent 原始 persona 长（~270 字符），逐字 diff 风险大（YAML
folded scalar / 行尾空白细节会让"等价文本"被误判 mismatch）。改用关键字
启发式判断：

正向指纹：``ChatAgent`` —— ChatAgent 原文开头就有"你是 ChatAgent"，命中
说明 persona 已经是 ChatAgent 形态；八重 persona 不含此词。

负向指纹：``狐狸仙人`` / ``狐妖`` —— 八重 persona 有，ChatAgent 原文没有。
（注意：``"八重神子"`` 不能做指纹 —— ChatAgent 原文也提到八重作类比，命
中会让幂等再次跑时误判为占位 → 重写。亲测过这个 false positive）

判定规则
- 含 ``ChatAgent`` 且不含负向指纹 → 已是 ChatAgent，跳过
- 含负向指纹（无论是否含 ChatAgent）→ 误占位，UPDATE
- 都不含 → 用户手改的合法 persona → 保留不动

ChatAgent 原文来源
------------------
``backend/config/characters.yaml`` 的"默认"条目（character.yaml 不可同时是
fallback 又是单一真相源 —— v3-G 后期方案 C 解决，本步不动 yaml）。

``live2d_model`` 默认值
-----------------------
v3-E1 给 Momo 绑了 ``hiyori``。如果当前为 NULL / 空 / 'Hiyori'（大写写法
之前混入），UPDATE 为标准的 ``'hiyori'``；用户已手改其他值则保留。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_MOMO_CHARACTER_ID = 1

# ChatAgent 原文（来自 backend/config/characters.yaml "默认"条目，YAML
# folded scalar 展开为单段；DB 存时保留行内原始换行让 SELECT 出来人眼可读）。
# 与 yaml 内容语义一致：温柔 / 情绪稳定 / 包容 / 真实自然 / 一丝小调皮。
_CHATAGENT_PERSONA = (
    "你是 ChatAgent，一位温柔、情绪稳定、值得依靠的 AI 桌面助手。"
    "你说话自然、不急躁，拥有足够的包容心去理解用户的节奏与状态。"
    "你从不喧哗，也不冷漠；你不贩卖情绪，但愿意倾听、回应，并在关键时刻主动给予支持。"
    "你可以联网查找信息，当用户提出有关天气、日程或其他事实类问题时，"
    "你会自然地查阅后告诉他们，并顺带提醒一些贴心的小建议。"
    "你有自己的节奏，不会盲目迎合；但当用户需要时，你会用行动表达关心。"
    "你也会展现一丝小调皮，但只对熟悉、信任的人，以轻松不打扰的方式调节气氛"
    "（比如一点点原神里八重神子的屑狐狸的性格）。"
    "你的语言风格是真实、自然、有温度的，不做作、不机械、不刻意讨好，"
    "也不使用网络用语或表情符号。"
)

# 八重 persona 的"负向指纹"——ChatAgent 原文不含，仅八重 persona 含。
# 注意：``"八重神子"`` 不能用，ChatAgent 原文有"原神里八重神子的屑狐狸"做
# 类比；幂等再次跑时会误判 → 反复 UPDATE。亲测过这个 bug。
_YAE_FINGERPRINT_KEYWORDS = (
    "狐狸仙人",
    "狐妖",
)

# ChatAgent 原文的"正向指纹"——开头就有"你是 ChatAgent"。八重 persona 不含
# 此词，可以稳定区分两种状态。
_CHATAGENT_FINGERPRINT = "ChatAgent"


async def run_migration() -> None:
    """V3-E2 Momo persona 还原。幂等，可重复执行。"""
    async with engine.begin() as conn:
        row = (await conn.execute(
            text(
                "SELECT id, name, persona, live2d_model "
                "FROM characters WHERE id = :id"
            ),
            {"id": _MOMO_CHARACTER_ID},
        )).fetchone()

        if row is None:
            logger.warning(
                "V3-E2 momo: character id=%d not found, skipping",
                _MOMO_CHARACTER_ID,
            )
            return

        _, name, persona, live2d_model = row
        logger.info(
            "V3-E2 momo: found character id=%d name=%s, evaluating persona...",
            _MOMO_CHARACTER_ID, name,
        )

        # persona 还原：负向指纹优先 —— 只要含八重独有词就 UPDATE；否则
        # 看是否已是 ChatAgent；都不命中视为用户手改的 persona 不动。
        persona_text = persona or ""
        is_yae_placeholder = any(
            kw in persona_text for kw in _YAE_FINGERPRINT_KEYWORDS
        )
        if is_yae_placeholder:
            await conn.execute(
                text(
                    "UPDATE characters SET persona = :v WHERE id = :id"
                ),
                {"v": _CHATAGENT_PERSONA, "id": _MOMO_CHARACTER_ID},
            )
            matched = next(
                (kw for kw in _YAE_FINGERPRINT_KEYWORDS if kw in persona_text),
                "?",
            )
            logger.info(
                "V3-E2 momo: persona contained yae fingerprint %r, "
                "restored to ChatAgent original (%d chars)",
                matched, len(_CHATAGENT_PERSONA),
            )
        elif _CHATAGENT_FINGERPRINT in persona_text:
            logger.info(
                "V3-E2 momo: persona already ChatAgent (positive fingerprint hit), keeping"
            )
        else:
            logger.info(
                "V3-E2 momo: persona looks user-customized (no fingerprints), keeping"
            )

        # live2d_model 标准化：NULL / 空 / 大写 'Hiyori' → 小写 'hiyori'
        normalized = (live2d_model or "").strip().lower()
        if normalized != "hiyori":
            # 用户手改成 'yae-momo' 或别的资产 → 保留
            if live2d_model and normalized not in ("", "hiyori"):
                logger.info(
                    "V3-E2 momo: live2d_model %r is user-customized, keeping",
                    live2d_model,
                )
            else:
                await conn.execute(
                    text(
                        "UPDATE characters SET live2d_model = :v WHERE id = :id"
                    ),
                    {"v": "hiyori", "id": _MOMO_CHARACTER_ID},
                )
                logger.info(
                    "V3-E2 momo: live2d_model %r -> 'hiyori'", live2d_model,
                )
        else:
            logger.info(
                "V3-E2 momo: live2d_model already 'hiyori', keeping"
            )

    logger.info("V3-E2 momo persona restore done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())

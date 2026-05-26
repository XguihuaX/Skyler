"""v4.0.0 ship-call: Mai (cid=1) 回退纯中文 pipeline。

# 背景
v4 persona segment2 ja pipeline(D1/D1.1/seg2-1/2/3)经多版仍未稳定:
- 话痨(ja 意群粒度强制塞太多)
- 中日内容偶有混在同一 ``<ja>`` tag(D1.1 已修但留尾)
- Mai 复刻日语 voice 在合成短中文时音色错乱(seg2 前老 bug)

v4.0.0 ship-call:Mai(cid=1)放弃日语,回到纯中文 voice。
- persona 完全不动(身份/语气/禁忌一样)
- 仅 ``voice_model`` 改:换中文内置音色 ``longyumi_v3`` + ``tts_language='zh'``
- ``tts_language='zh'`` 让 ``layer_a.j2`` 的 ja 分支 ``{% if %}`` 不命中
  → 不再注入 ja directive(意群粒度强制) → 话痨根因消失
- ``ws.py`` / ``proactive/engine.py`` 的 ``if tts_language in ('ja','en')``
  门控让 ``sentence_merge`` 在 zh 路径下不介入 → 回到逐句流式(字幕跟手)
- ``extract_tts_text`` 在 zh 路径返回 ``strip_all_for_tts(raw_text)``
  (pre-segment2 原行为) → 中文正文直接送 TTS

ja 路径代码全部保留(``sentence_merge.py``、``extract_tts_text`` ja/en 分支、
``layer_a.j2`` ja/en directive、``SUSPICIOUS_TAG`` 的 ``<ja>``/``<en>`` 白名单),
留给 v4.1 用后处理翻译架构重做。

# 与 segment2 老迁移的关系
``v4_persona_segment2_mai_ja.py`` 仍在 main.py 启动序列中且**保留不动**。
它按 ``voice = cosyvoice-v3.5-plus-bailian-a19f...`` 匹配标 ``tts_language=ja``。
本迁移在它**之后**跑(main.py 注册顺序保证),无条件把 cid=1 写回
``longyumi_v3 / zh`` —— 即使 seg2 迁移把 ja 标到 cid=1(因 voice 还是 a19f),
本迁移随后再覆盖一次。一旦 cid=1 voice 已经是 ``longyumi_v3``,seg2 的 WHERE
``voice = a19f...`` 不匹配,自然不会再碰 cid=1;只本迁移做 idempotent 校验。

cid=101(真实"樱岛麻衣"character)仍持 ja voice + tts_language=ja,
留给 v4.1 复用,本迁移**不动**它(WHERE id = 1)。

# 幂等
WHERE 子句:``voice != 'longyumi_v3' OR tts_language != 'zh'`` 之一不满足才 UPDATE。
重复跑只在偏离时纠正,已对齐的行 rowcount=0。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_CID = 1
_TARGET_VOICE_MODEL = (
    '{"provider":"cosyvoice","voice":"longyumi_v3",'
    '"instruct_supported":false,"tts_language":"zh"}'
)


_UPDATE_SQL = """
UPDATE characters
SET voice_model = :voice_model
WHERE id = :cid
  AND (
      voice_model IS NULL
      OR voice_model = ''
      OR json_extract(voice_model, '$.provider') IS NULL
      OR json_extract(voice_model, '$.provider') = 'cosyvoice'
  )
  AND (
      voice_model IS NULL
      OR voice_model = ''
      OR json_extract(voice_model, '$.voice') IS NULL
      OR json_extract(voice_model, '$.voice') != 'longyumi_v3'
      OR json_extract(voice_model, '$.tts_language') IS NULL
      OR json_extract(voice_model, '$.tts_language') != 'zh'
  )
"""
# INV-11 Stage -1 hotfix (2026-05-25):WHERE 上半段加 provider scope。
# 原 migration ship-call 目标是把误标 ja 的 cid=1 cosyvoice voice 推回
# longyumi_v3/zh,**不应**强制 cid=1 永远绑 cosyvoice。漏 scope 导致
# INV-11 Stage -1 切 cid=1 → gsv 后每次 lifespan startup 都回滚。
# 加 `provider IN (NULL, 'cosyvoice')` 守卫:仅在 NULL / 已是 cosyvoice
# 体系时 nudge voice/lang。切去 gsv/fish/edge/sovits 后 short-circuit
# 不动 voice_model。语义跟 ship-call 本意一致。
# 实验后清理:`git checkout` 本文件 restore origin(或保留此 hotfix,
# 因为它本来就是 design bug 的 surgical fix)。


async def run_migration() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(
            text(_UPDATE_SQL),
            {"voice_model": _TARGET_VOICE_MODEL, "cid": _CID},
        )
        rowcount = getattr(result, "rowcount", 0) or 0
    logger.info(
        "[v4_0_0_mai_revert_zh] cid=%d → longyumi_v3/zh; rows_updated=%d",
        _CID, rowcount,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())

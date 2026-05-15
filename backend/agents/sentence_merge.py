"""Bugfix-Segment2-3 — short-sentence merge buffer.

ja/en TTS 模式下 LLM 偶发把回复切碎成 2-5 字短句(eg ``"嗯。"`` + ``"去吧。"`` +
``"我不吵你。"``),每个独立 sentence yield → cosyvoice 复刻 voice 对极短文本
合成质量崩(噪声 / 错乱音色)。

本模块包一个 async generator wrapper,在 ``_chat_agent.stream()`` 的 yield
output 上做短句合并:
  * 单 sentence 的**字幕字数**(剥所有 meta tag 后)< short_threshold 且
    buffer 非空 → 累积到 buffer 不立即 yield
  * buffer 累积到 ≥ flush_threshold → flush yield
  * 长 sentence(≥ flush_threshold)→ 先 flush 旧 buffer,然后立即 yield 新
  * stream 结束 → flush 残余 buffer

**长度按字幕字数(strip_ja_en_tags_for_subtitle(strip_all_for_tts(...)))测量**,
而非 raw sentence(含 ``<ja>...</ja>`` tag 的 raw len 偏大,会误判为"长")。

dict 项(``tool_use_start`` / ``tool_use_done`` typed event)**pass-through**:
flush 当前 buffer 后原样 yield dict,保持事件顺序。

调用约束(caller 决定何时启用):
  * **仅 ja/en 模式**调用本 wrapper;zh 模式 pass-through,避免增加字幕 latency
  * caller 自己读 character.voice_model.tts_language 后决定 wrap or 直 stream
  * 中间不要再插其他 buffer(语义清晰)
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Union

from backend.utils.text_filters import (
    strip_all_for_tts,
    strip_ja_en_tags_for_subtitle,
)

logger = logging.getLogger(__name__)


# 默认阈值(按字幕字数)。Bugfix-segment2-3 实测 Mai 复刻 voice 对 5 字以下
# 文本质量崩,对 10+ 字稳定。flush 阈值 15 让 2-3 句短意群合并送 TTS,平衡
# 流式体验与音频质量。
DEFAULT_SHORT_THRESHOLD = 8
DEFAULT_FLUSH_THRESHOLD = 15


def _subtitle_len(sentence: str) -> int:
    """测 sentence 的**用户可见**字数(剥 ja/en/meta tag 后的中文字幕长度)。

    用于判断 sentence 是否"短到需要合并"。raw len 含 ``<ja>...</ja>`` 等 meta
    tag 字符,会高估真实可读长度;只有字幕长度才反映 TTS 输入意群长度。
    """
    if not sentence:
        return 0
    cleaned = strip_ja_en_tags_for_subtitle(strip_all_for_tts(sentence))
    return len(cleaned.strip()) if cleaned else 0


async def merge_short_sentences(
    stream: AsyncGenerator[Union[str, dict], None],
    *,
    short_threshold: int = DEFAULT_SHORT_THRESHOLD,
    flush_threshold: int = DEFAULT_FLUSH_THRESHOLD,
) -> AsyncGenerator[Union[str, dict], None]:
    """合并短 sentence 防 ja/en 模式下 TTS 短音频崩。

    Args:
        stream: ``_chat_agent.stream()`` 的 yield generator;含 ``str`` sentence
            与 ``dict`` tool event。
        short_threshold: 字幕字数 ``<`` 此值的 sentence 视为"短",需合并(默认 8)
        flush_threshold: buffer 字幕字数 ``≥`` 此值时 flush(默认 15)

    Yields:
        同 ``stream``,但短 sentence 已合并;dict 原样 pass-through。

    Logs(debug):每次合并 / flush 都 log 一行便于 dogfood 调试。
    """
    buffer = ""

    async for item in stream:
        # dict (typed WS event) pass-through;flush 当前 buffer 保持顺序
        if isinstance(item, dict):
            if buffer:
                logger.debug(
                    "[sentence_merge] flushing buffer (%d sub-chars) before dict event",
                    _subtitle_len(buffer),
                )
                yield buffer
                buffer = ""
            yield item
            continue

        sentence = item
        if not isinstance(sentence, str):
            # 防御:未来 chat agent 可能 yield 其他类型 → 原样穿透 + flush
            if buffer:
                yield buffer
                buffer = ""
            yield sentence  # type: ignore[unreachable]
            continue

        s_sub = _subtitle_len(sentence)

        # 短 sentence + buffer 非空 → 累积
        if s_sub < short_threshold and buffer:
            buffer += sentence
            buf_sub = _subtitle_len(buffer)
            logger.debug(
                "[sentence_merge] merged short sentence (%d sub-chars) "
                "into buffer (%d sub-chars total)", s_sub, buf_sub,
            )
            if buf_sub >= flush_threshold:
                logger.debug("[sentence_merge] flushed buffer at %d sub-chars", buf_sub)
                yield buffer
                buffer = ""
            continue

        # 长 sentence 或第一个短(buffer 空)→ flush 旧 buffer + 起新
        if buffer:
            logger.debug(
                "[sentence_merge] flushing buffer (%d sub-chars) before "
                "new sentence (%d sub-chars)", _subtitle_len(buffer), s_sub,
            )
            yield buffer
            buffer = ""
        buffer = sentence
        if s_sub >= flush_threshold:
            # 长 sentence 不需要等,立即 flush
            logger.debug(
                "[sentence_merge] passthrough long sentence (%d sub-chars)",
                s_sub,
            )
            yield buffer
            buffer = ""

    # stream 结束 → flush 残余
    if buffer:
        logger.debug(
            "[sentence_merge] flushing residue at stream end (%d sub-chars)",
            _subtitle_len(buffer),
        )
        yield buffer

"""v3.5 chunk 10 — memory entry validator + quality filter pipeline。

按 chunk 11 ``profile_validator`` 同 spirit：

  * Hard reject (entry 不进入 returned list)
    1. JSON parse 失败 (markdown fence 容错后)
    2. 顶层不是 list
    3. 单 entry 不是 dict
    4. schema 字段缺失 / 类型错
    5. type 不在 ``ALLOWED_TYPES``
    6. content 长度超出 ``MIN_CONTENT_LEN .. MAX_CONTENT_LEN``
    7. content 命中 ``SUSPICIOUS_TAG_RE``
    8. confidence 低于阈值
    9. 与现有 memory 向量相似度 > dup_threshold
    10. (可选) LLM judge "对未来有用" 返 False

  * Soft warn (entry 进入 returned list + log)
    a. 反推词命中（chunk 11 14 词清单）

无 reject 全保留；每个 reject 都 log 让运维能看到 worker 行为。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from backend.utils.text_filters import SUSPICIOUS_TAG_RE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema constraints
# ---------------------------------------------------------------------------

ALLOWED_TYPES = frozenset(["fact", "preference", "event", "commitment"])

MIN_CONTENT_LEN = 5
MAX_CONTENT_LEN = 200

# 与 chunk 11 profile_validator 同源 14 词
_BACKINFERENCE_KEYWORDS = (
    "感觉", "情绪", "印象", "陪伴", "亲密", "需要被",
    "渴望", "温柔", "细腻", "敏感", "脆弱", "依赖",
    "孤独", "情感",
)


# ---------------------------------------------------------------------------
# Stage 1: JSON parse + markdown fence tolerance
# ---------------------------------------------------------------------------


def parse_extractor_output(raw: str) -> Optional[list]:
    """Parse LLM raw string into ``list`` (entries) or ``None`` (reject)。

    容错：自动剥 ```` ```json ... ``` ```` 围栏（chunk 11 同 pattern）。
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    if not cleaned:
        return None

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[extractor_validator] JSON parse failed err=%s preview=%r",
            exc, cleaned[:200],
        )
        return None

    # LLM 偶发不听话输出 dict 包含 ``entries`` key 而非顶层 list；
    # 容忍 ``{"entries": [...]}`` 这种常见 quirk
    if isinstance(parsed, dict):
        if isinstance(parsed.get("entries"), list):
            parsed = parsed["entries"]
        else:
            logger.warning(
                "[extractor_validator] top-level dict without 'entries' key, "
                "preview=%r",
                cleaned[:200],
            )
            return None

    if not isinstance(parsed, list):
        logger.warning(
            "[extractor_validator] top-level not list, got %s",
            type(parsed).__name__,
        )
        return None

    return parsed


# ---------------------------------------------------------------------------
# Stage 2: per-entry schema + content sanity
# ---------------------------------------------------------------------------


def _validate_entry_schema(
    entry: Any, *, user_id: str = "?",
) -> Optional[dict]:
    """单 entry schema 校验 + normalize。返 cleaned dict 或 None（reject）。

    输出 dict 含：
      * ``type``       string ∈ ALLOWED_TYPES
      * ``content``    stripped 5-200 字符 string，无 SUSPICIOUS tag
      * ``confidence`` float ∈ [0, 1]
    """
    if not isinstance(entry, dict):
        logger.warning(
            "[extractor_validator] entry not dict user=%s type=%s",
            user_id, type(entry).__name__,
        )
        return None

    # type
    etype = entry.get("type")
    if not isinstance(etype, str) or etype not in ALLOWED_TYPES:
        logger.warning(
            "[extractor_validator] invalid entry_type user=%s got=%r",
            user_id, etype,
        )
        return None

    # content
    content = entry.get("content")
    if not isinstance(content, str):
        logger.warning(
            "[extractor_validator] content not string user=%s type=%s",
            user_id, type(content).__name__,
        )
        return None
    content = content.strip()
    if not (MIN_CONTENT_LEN <= len(content) <= MAX_CONTENT_LEN):
        logger.warning(
            "[extractor_validator] content length reject user=%s "
            "len=%d (need %d..%d)",
            user_id, len(content), MIN_CONTENT_LEN, MAX_CONTENT_LEN,
        )
        return None
    if SUSPICIOUS_TAG_RE.search(content):
        logger.warning(
            "[extractor_validator] SUSPICIOUS_TAG reject user=%s preview=%r",
            user_id, content[:120],
        )
        return None

    # confidence
    conf_raw = entry.get("confidence")
    if isinstance(conf_raw, bool) or not isinstance(conf_raw, (int, float)):
        logger.warning(
            "[extractor_validator] confidence not number user=%s got=%r",
            user_id, conf_raw,
        )
        return None
    confidence = float(conf_raw)
    if not (0.0 <= confidence <= 1.0):
        logger.warning(
            "[extractor_validator] confidence out of [0,1] user=%s got=%s",
            user_id, confidence,
        )
        return None

    # Soft warn: backinference keywords (不 reject，fail-open)
    hits = [kw for kw in _BACKINFERENCE_KEYWORDS if kw in content]
    if hits:
        logger.warning(
            "[extractor_validator] backinference keywords in entry "
            "user=%s hits=%s preview=%r — accepted (fail-open)",
            user_id, sorted(set(hits)), content[:120],
        )

    return {
        "type": etype,
        "content": content,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Stage 3: confidence threshold + duplicate detection
# ---------------------------------------------------------------------------


async def _is_duplicate(
    content: str,
    existing_contents: list[str],
    dup_threshold: float,
) -> bool:
    """向量相似度 > ``dup_threshold`` 视同重复。

    复用 ``backend.memory.long_term._encode`` 算 cosine。空 ``existing_contents``
    直接返 False。
    """
    if not existing_contents:
        return False
    try:
        import numpy as np
        from backend.memory.long_term import _cosine, _encode
        new_vec = await _encode(content)
        for ex in existing_contents:
            if not ex:
                continue
            ex_vec = await _encode(ex)
            if _cosine(new_vec, ex_vec) > dup_threshold:
                return True
    except Exception:
        logger.exception(
            "[extractor_validator] dup check failed; treating as not-dup"
        )
    return False


# ---------------------------------------------------------------------------
# Top-level filter pipeline
# ---------------------------------------------------------------------------


async def validate_and_filter_entries(
    raw: str,
    *,
    user_id: str,
    min_confidence: float,
    dup_threshold: float,
    existing_contents: list[str],
    llm_judge: Optional[callable] = None,
) -> list[dict]:
    """端到端：raw LLM string → filtered entries list。

    Args:
        raw:               LLM 原始 string（commit 3 ``call_extraction_llm`` 输出）
        user_id:           log 用
        min_confidence:    confidence < N → reject
        dup_threshold:     向量相似度 > N → 视同重复 → reject
        existing_contents: 已有 memory contents（cosine 比对源）
        llm_judge:         可选 ``async (content) -> bool`` 第 5 道 filter；
                           None 时跳过

    Returns:
        cleaned dicts list（每个含 ``type`` / ``content`` / ``confidence``）。
    """
    parsed = parse_extractor_output(raw)
    if parsed is None:
        logger.warning(
            "[extractor_validator] parse failed for user=%s, dropping batch",
            user_id,
        )
        return []

    out: list[dict] = []
    for idx, raw_entry in enumerate(parsed):
        cleaned = _validate_entry_schema(raw_entry, user_id=user_id)
        if cleaned is None:
            continue

        if cleaned["confidence"] < min_confidence:
            logger.info(
                "[extractor_validator] low confidence reject user=%s idx=%d "
                "conf=%.2f min=%.2f preview=%r",
                user_id, idx, cleaned["confidence"], min_confidence,
                cleaned["content"][:80],
            )
            continue

        if await _is_duplicate(cleaned["content"], existing_contents,
                               dup_threshold):
            logger.info(
                "[extractor_validator] duplicate reject user=%s idx=%d "
                "preview=%r",
                user_id, idx, cleaned["content"][:80],
            )
            continue

        if llm_judge is not None:
            try:
                useful = await llm_judge(cleaned["content"])
            except Exception:
                logger.exception(
                    "[extractor_validator] llm_judge threw user=%s idx=%d "
                    "— accepting entry (fail-open)",
                    user_id, idx,
                )
                useful = True
            if not useful:
                logger.info(
                    "[extractor_validator] llm_judge reject user=%s idx=%d "
                    "preview=%r",
                    user_id, idx, cleaned["content"][:80],
                )
                continue

        out.append(cleaned)
        # Keep growing existing_contents so dup check sees this batch's own
        # earlier accepts as well (intra-batch dedup)
        existing_contents.append(cleaned["content"])

    return out


__all__ = [
    "ALLOWED_TYPES",
    "MAX_CONTENT_LEN",
    "MIN_CONTENT_LEN",
    "parse_extractor_output",
    "validate_and_filter_entries",
]

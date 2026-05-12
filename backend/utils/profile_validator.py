"""v3.5 chunk 11 — profile_data JSON validator。

严格规则（reject = 返 None，调用方保留旧 profile）：

  1. JSON 解析失败 → reject
  2. 顶层不是 dict → reject
  3. schema 必填字段缺失 → reject（7 字段全部必填）
  4. 字段类型错（string 字段是 list / list 字段是 string / None list / ...）
     → reject
  5. 任一 string 字段 / list[string] 字段命中 ``SUSPICIOUS_TAG_RE``
     → reject + log warning

容忍（不 reject）：

  6. schema 外字段 → **自动剥离** + log info
  7. 任一 string 字段含明显反推词（感觉/情绪/印象/反推性描述）
     → log warning（fail-open，让用户在 UI 手动编辑修正）
  8. string 字段空白字符串 → 视同 None
  9. list 字段含 None / 空字符串 → 过滤掉
  10. list 字段非字符串元素 → 过滤掉

返回 dict 时一定满足 schema：所有 7 字段都在，类型严格正确。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from backend.utils.profile_schema import (
    PROFILE_SCHEMA_V1,
    is_list_field,
    is_string_field,
)
from backend.utils.text_filters import SUSPICIOUS_TAG_RE

logger = logging.getLogger(__name__)


#: 反推性描述关键字（fail-open warning，不 reject）。
#:
#: 这些词典型出现在 chunk 9 治标方案没消尽的"温度感"描述里。validator 不
#: reject 是因为它们不是 *违法*，只是不该出现在结构化档案中 —— LLM 偶发
#: 写入，让用户在 UI 手动剔除即可。
_BACKINFERENCE_KEYWORDS = (
    "感觉", "情绪", "印象", "陪伴", "亲密", "需要被",
    "渴望", "温柔", "细腻", "敏感", "脆弱", "依赖",
    "孤独", "情感",
)


def _has_suspicious_tag(value: str) -> bool:
    return bool(SUSPICIOUS_TAG_RE.search(value))


def _check_backinference(values: list[str]) -> list[str]:
    """返回命中反推词的 keyword 列表（用于 log warning）。"""
    hits: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        for kw in _BACKINFERENCE_KEYWORDS:
            if kw in v:
                hits.append(kw)
    return hits


def _normalize_string_value(value: Any) -> Optional[str]:
    """Normalize a single string|null cell.

    Returns:
      - ``None`` if value is None / not str / blank after strip
      - stripped non-empty string otherwise
    Caller still has to reject SUSPICIOUS hits separately.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s if s else None


def _normalize_list_value(value: Any) -> Optional[list[str]]:
    """Normalize a list[string] cell.

    Returns:
      - ``None`` if value is None / not list (caller will reject)
      - filtered list[str] otherwise (drops None / non-str / blank items)
    """
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if s:
            out.append(s)
    return out


def validate_profile_json(raw: str, *, user_id: str = "unknown") -> Optional[dict]:
    """Parse + validate LLM-emitted profile JSON against PROFILE_SCHEMA_V1.

    Returns ``None`` on hard reject (caller should keep old profile). Returns
    a dict with exactly the 7 schema keys (canonical types) on success.

    Args:
        raw:     Raw LLM text. Strips optional ```json fences first.
        user_id: For logging (helps trace cross-user failures in prod log).

    Hard reject paths log at WARNING. Soft fail-open paths (extra fields,
    backinference keywords) log at INFO/WARNING but still return the cleaned
    dict.
    """
    # 1. Strip optional ``` json fences
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        # 去 markdown fence（如果 LLM 不听话）
        cleaned = re.sub(
            r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    if not cleaned:
        logger.warning("[profile_validator] empty input user=%s", user_id)
        return None

    # 2. JSON parse
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[profile_validator] JSON parse failed user=%s err=%s preview=%r",
            user_id, exc, cleaned[:200],
        )
        return None

    # 3. Top-level dict
    if not isinstance(parsed, dict):
        logger.warning(
            "[profile_validator] top-level not dict user=%s type=%s",
            user_id, type(parsed).__name__,
        )
        return None

    # 4. Strip extra fields (容忍 + log)
    extras = [k for k in parsed.keys() if k not in PROFILE_SCHEMA_V1]
    if extras:
        logger.info(
            "[profile_validator] stripping extra fields user=%s fields=%s",
            user_id, extras,
        )

    # 5. Required field presence + type check + SUSPICIOUS sweep
    out: dict[str, Any] = {}
    suspicious_hit = False
    all_strings_for_backref: list[str] = []

    for key, type_tag in PROFILE_SCHEMA_V1.items():
        if key not in parsed:
            logger.warning(
                "[profile_validator] missing required field user=%s key=%s",
                user_id, key,
            )
            return None
        value = parsed[key]
        if is_string_field(key):
            norm = _normalize_string_value(value)
            # type sanity: 原 value 非 None 又非 str → reject
            if value is not None and not isinstance(value, str):
                logger.warning(
                    "[profile_validator] type error user=%s key=%s "
                    "expected string|null got %s",
                    user_id, key, type(value).__name__,
                )
                return None
            if norm and _has_suspicious_tag(norm):
                logger.warning(
                    "[profile_validator] SUSPICIOUS tag in string field "
                    "user=%s key=%s preview=%r",
                    user_id, key, norm[:120],
                )
                suspicious_hit = True
            if norm:
                all_strings_for_backref.append(norm)
            out[key] = norm
        elif is_list_field(key):
            norm = _normalize_list_value(value)
            if norm is None:
                logger.warning(
                    "[profile_validator] type error user=%s key=%s "
                    "expected list[string] got %s",
                    user_id, key, type(value).__name__,
                )
                return None
            for item in norm:
                if _has_suspicious_tag(item):
                    logger.warning(
                        "[profile_validator] SUSPICIOUS tag in list item "
                        "user=%s key=%s item=%r",
                        user_id, key, item[:120],
                    )
                    suspicious_hit = True
                all_strings_for_backref.append(item)
            out[key] = norm
        else:
            # 不会走到（PROFILE_SCHEMA_V1 只有两种 type_tag）
            logger.error(
                "[profile_validator] schema bug? unknown type_tag user=%s key=%s "
                "tag=%s",
                user_id, key, type_tag,
            )
            return None

    if suspicious_hit:
        return None  # SUSPICIOUS_TAG_RE 命中 reject

    # 6. Soft warning: backinference keywords
    bi_hits = _check_backinference(all_strings_for_backref)
    if bi_hits:
        logger.warning(
            "[profile_validator] backinference keywords detected user=%s "
            "hits=%s — accepted (fail-open) but UI editor should clean",
            user_id, sorted(set(bi_hits)),
        )

    return out


__all__ = ["validate_profile_json"]

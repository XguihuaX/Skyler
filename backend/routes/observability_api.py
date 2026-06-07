"""Bugfix-4 — Observability REST API.

GET /api/observability/tts/usage[?range=today|month]
GET /api/observability/tts/recent_calls[?limit=20]
GET /api/observability/system/resources
GET /api/observability/boot-summary   (第三刀 · 进入动画喂数据 · BootTracker 真实 snapshot)
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SourceUsage(BaseModel):
    calls: int
    chars: int
    cost: float


class AnomalyCall(BaseModel):
    id: int
    timestamp: Optional[str] = None
    source: Optional[str] = None
    character_id: Optional[int] = None
    voice: Optional[str] = None
    input_chars: int
    input_preview: Optional[str] = None
    success: bool
    error_message: Optional[str] = None


class TtsUsageResponse(BaseModel):
    range: str
    total_calls: int
    total_chars: int
    total_cost_yuan: float
    by_source: dict[str, SourceUsage]
    avg_chars_per_call: Optional[int] = None
    anomaly_calls: List[AnomalyCall]


class RecentCall(BaseModel):
    id: int
    timestamp: Optional[str] = None
    source: Optional[str] = None
    character_id: Optional[int] = None
    voice: Optional[str] = None
    model: Optional[str] = None
    input_chars: int
    input_preview: Optional[str] = None
    cost_estimate: Optional[float] = None
    success: bool
    error_message: Optional[str] = None


class RecentCallsResponse(BaseModel):
    calls: List[RecentCall]


class SystemResourcesResponse(BaseModel):
    has_psutil: bool
    backend_rss_mb: Optional[float] = None
    backend_cpu_percent: Optional[float] = None
    system_total_ram_mb: Optional[float] = None
    system_used_ram_mb: Optional[float] = None
    system_ram_percent: Optional[float] = None
    whisper_loaded: bool
    whisper_size: Optional[str] = None
    whisper_disk_mb: Optional[float] = None
    net_recv_kbps: Optional[float] = None
    net_sent_kbps: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/observability/tts/usage", response_model=TtsUsageResponse)
async def get_tts_usage(range: str = Query("today", pattern="^(today|month|all)$")) -> Any:
    from backend.observability.tts_aggregate import aggregate_usage
    try:
        data = await aggregate_usage(range)
    except Exception as exc:
        logger.exception("[observability] aggregate_usage failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return data


@router.get("/observability/tts/recent_calls", response_model=RecentCallsResponse)
async def get_recent_calls(limit: int = Query(20, ge=1, le=200)) -> Any:
    from backend.observability.tts_aggregate import list_recent_calls
    try:
        calls = await list_recent_calls(limit)
    except Exception as exc:
        logger.exception("[observability] list_recent_calls failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"calls": calls}


@router.get("/observability/system/resources", response_model=SystemResourcesResponse)
async def get_system_resources() -> Any:
    from backend.observability import system as sys_mod
    snapshot = sys_mod.collect()
    return sys_mod.to_dict(snapshot)


@router.get("/observability/boot-summary")
async def get_boot_summary() -> Any:
    """第三刀 · 进入动画喂数据 · 返回 BootTracker 真实 snapshot。

    marks 顺序 = mark 调用顺序 = 真实 eager 阶段顺序(给 loading sequence 按
    序 reveal)。bg = 背景 warmup 完成耗时(embedding / whisper · 完成前为 [])。
    total_ms = eager 总时(yield 之前)。
    """
    from backend.utils.boot_tracker import get_tracker
    return get_tracker().get_snapshot()

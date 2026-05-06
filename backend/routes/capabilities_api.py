"""v3-G chunk 0 — REST endpoints for the Capability Registry.

* ``GET  /api/capabilities``                  → 列出全部 user-visible capability
  + 当前 health 状态（并发跑所有 health_check）
* ``POST /api/capabilities/{name}/healthcheck`` → 单个 capability health 刷新
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.capabilities import Capability, CapabilityRegistry

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CapabilityDTO(BaseModel):
    """Capability 序列化形态。handler / health_check 不出 wire（callable 不可序列化）。"""

    name: str
    display_name: str
    description: str
    category: str
    consumers: list[str]
    trigger_modes: list[str]
    icon: str
    user_visible: bool
    has_health_check: bool
    health: dict[str, Any]


class CapabilitiesResponse(BaseModel):
    capabilities: list[CapabilityDTO]
    by_category: dict[str, list[CapabilityDTO]]


class HealthCheckResponse(BaseModel):
    name: str
    health: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_dto(cap: Capability, health: dict[str, Any]) -> CapabilityDTO:
    return CapabilityDTO(
        name=cap.name,
        display_name=cap.display_name,
        description=cap.description,
        category=cap.category,
        consumers=[c.value for c in cap.consumers],
        trigger_modes=[t.value for t in cap.trigger_modes],
        icon=cap.icon,
        user_visible=cap.user_visible,
        has_health_check=cap.health_check is not None,
        health=health,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/capabilities", response_model=CapabilitiesResponse)
async def list_capabilities() -> CapabilitiesResponse:
    """返回 user-visible 的 capability 列表 + 即时 health 状态。"""
    registry = CapabilityRegistry()
    visible = registry.list_user_visible()
    health_map = await registry.health_check_all()

    dtos = [_to_dto(c, health_map.get(c.name, {"status": "unknown"})) for c in visible]

    by_category: dict[str, list[CapabilityDTO]] = {}
    for dto in dtos:
        by_category.setdefault(dto.category, []).append(dto)

    return CapabilitiesResponse(capabilities=dtos, by_category=by_category)


@router.post(
    "/capabilities/{name}/healthcheck",
    response_model=HealthCheckResponse,
)
async def healthcheck_capability(name: str) -> HealthCheckResponse:
    """单独刷新某个 capability 的 health 状态（前端"刷新"按钮用）。"""
    registry = CapabilityRegistry()
    cap = registry.get(name)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"capability {name!r} not found")
    health = await registry.health_check_one(name)
    return HealthCheckResponse(name=name, health=health)

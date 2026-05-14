"""Bugfix-3.1 — AI Providers REST API.

Endpoints:
  Vendors:
    GET    /api/ai-vendors                    list all + has_credential
    POST   /api/ai-vendors                    create custom vendor
    PATCH  /api/ai-vendors/{id}               update vendor fields
    DELETE /api/ai-vendors/{id}               delete custom vendor
    POST   /api/ai-vendors/{id}/credentials   set / update vendor key
    DELETE /api/ai-vendors/{id}/credentials   clear vendor key

  Providers:
    GET    /api/ai-providers?type=llm         list (optionally grouped by vendor)
    POST   /api/ai-providers                  create custom provider
    PATCH  /api/ai-providers/{id}             update fields
    DELETE /api/ai-providers/{id}             delete custom provider
    POST   /api/ai-providers/{id}/activate    switch active per-type

Validation:
  - vendor pk 必须 ``^[a-z0-9_-]+$`` (URL friendly), 3-32 chars
  - type ∈ {llm, asr, tts}
  - DELETE builtin → 403
  - activate without credential → 400 with reason='no_credential'
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import ai_providers as svc

router = APIRouter()


_VENDOR_ID_RE = re.compile(r"^[a-z0-9_-]+$")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class VendorOut(BaseModel):
    id: str
    name: str
    vendor_kind: str
    default_endpoint: Optional[str] = None
    credential_key_name: str
    endpoint_env_name: Optional[str] = None  # bugfix-3.2.6
    color: Optional[str] = None
    icon: Optional[str] = None
    has_credential: bool
    credential_source: str  # 'db' | 'env' | 'none'  bugfix-3.2.6


class VendorCreateBody(BaseModel):
    id: str = Field(..., min_length=3, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    default_endpoint: Optional[str] = None
    credential_key_name: str = Field(..., min_length=1, max_length=64)
    endpoint_env_name: Optional[str] = None  # bugfix-3.2.6
    color: Optional[str] = None
    icon: Optional[str] = None


class VendorPatchBody(BaseModel):
    name: Optional[str] = None
    default_endpoint: Optional[str] = None
    credential_key_name: Optional[str] = None
    endpoint_env_name: Optional[str] = None  # bugfix-3.2.6
    color: Optional[str] = None
    icon: Optional[str] = None


class CredentialSetBody(BaseModel):
    key_value: str = Field(..., min_length=1)


class ProviderOut(BaseModel):
    id: int
    vendor_id: Optional[str] = None
    type: str
    name: str
    model: str
    endpoint: Optional[str] = None
    extra_json: Optional[str] = None
    provider_kind: str
    enabled: bool
    is_active: bool


class VendorGroupOut(BaseModel):
    id: str
    name: str
    vendor_kind: str
    default_endpoint: Optional[str] = None      # bugfix-3.2.6 for modal use
    credential_key_name: str                     # bugfix-3.2.6 for modal use
    endpoint_env_name: Optional[str] = None     # bugfix-3.2.6
    has_credential: bool
    credential_source: str
    color: Optional[str] = None
    icon: Optional[str] = None
    providers: List[ProviderOut]


class ProvidersGroupedResponse(BaseModel):
    vendors: List[VendorGroupOut]
    # ungrouped 给 ASR / TTS 等 vendor_id=null 的(本 stage 暂无,留接口位)
    ungrouped: List[ProviderOut]


class ProviderCreateBody(BaseModel):
    vendor_id: Optional[str] = None
    type: str
    name: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=128)
    endpoint: Optional[str] = None
    extra_json: Optional[str] = None


class ProviderPatchBody(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    endpoint: Optional[str] = None
    extra_json: Optional[str] = None
    enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_vendor_out(v: svc.Vendor) -> VendorOut:
    return VendorOut(
        id=v.id, name=v.name, vendor_kind=v.vendor_kind,
        default_endpoint=v.default_endpoint,
        credential_key_name=v.credential_key_name,
        endpoint_env_name=v.endpoint_env_name,
        color=v.color, icon=v.icon,
        has_credential=v.has_credential,
        credential_source=v.credential_source,
    )


def _to_provider_out(p: svc.Provider) -> ProviderOut:
    return ProviderOut(
        id=p.id, vendor_id=p.vendor_id, type=p.type, name=p.name,
        model=p.model, endpoint=p.endpoint, extra_json=p.extra_json,
        provider_kind=p.provider_kind, enabled=p.enabled, is_active=p.is_active,
    )


# ---------------------------------------------------------------------------
# Vendor endpoints
# ---------------------------------------------------------------------------


@router.get("/ai-vendors", response_model=List[VendorOut])
async def list_vendors_endpoint() -> Any:
    rows = await svc.list_vendors()
    return [_to_vendor_out(v) for v in rows]


@router.post("/ai-vendors", response_model=VendorOut, status_code=201)
async def create_vendor_endpoint(body: VendorCreateBody) -> Any:
    if not _VENDOR_ID_RE.match(body.id):
        raise HTTPException(
            status_code=400,
            detail="vendor id must match ^[a-z0-9_-]+$",
        )
    if await svc.get_vendor(body.id) is not None:
        raise HTTPException(status_code=409, detail=f"vendor {body.id!r} already exists")
    v = await svc.create_vendor(
        id=body.id, name=body.name,
        default_endpoint=body.default_endpoint,
        credential_key_name=body.credential_key_name,
        endpoint_env_name=body.endpoint_env_name,
        color=body.color, icon=body.icon,
    )
    return _to_vendor_out(v)


@router.patch("/ai-vendors/{vendor_id}", response_model=VendorOut)
async def patch_vendor_endpoint(vendor_id: str, body: VendorPatchBody) -> Any:
    v = await svc.patch_vendor(
        vendor_id,
        name=body.name,
        default_endpoint=body.default_endpoint,
        credential_key_name=body.credential_key_name,
        endpoint_env_name=body.endpoint_env_name,
        color=body.color, icon=body.icon,
    )
    if v is None:
        raise HTTPException(status_code=404, detail=f"vendor {vendor_id!r} not found")
    return _to_vendor_out(v)


@router.delete("/ai-vendors/{vendor_id}", status_code=204)
async def delete_vendor_endpoint(vendor_id: str) -> None:
    result = await svc.delete_vendor(vendor_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail=f"vendor {vendor_id!r} not found")
    if result == "builtin":
        raise HTTPException(
            status_code=403,
            detail="cannot delete builtin vendor; disable providers individually",
        )


@router.post("/ai-vendors/{vendor_id}/credentials", status_code=204)
async def set_vendor_credential_endpoint(vendor_id: str, body: CredentialSetBody) -> None:
    ok = await svc.set_vendor_credential(vendor_id, body.key_value)
    if not ok:
        raise HTTPException(status_code=404, detail=f"vendor {vendor_id!r} not found")


@router.delete("/ai-vendors/{vendor_id}/credentials", status_code=204)
async def clear_vendor_credential_endpoint(vendor_id: str) -> None:
    if await svc.get_vendor(vendor_id) is None:
        raise HTTPException(status_code=404, detail=f"vendor {vendor_id!r} not found")
    await svc.clear_vendor_credential(vendor_id)


# ---------------------------------------------------------------------------
# Provider endpoints
# ---------------------------------------------------------------------------


@router.get("/ai-providers", response_model=ProvidersGroupedResponse)
async def list_providers_grouped_endpoint(
    type: Optional[str] = Query(None, pattern="^(llm|asr|tts)$"),
) -> Any:
    """Return providers grouped by vendor (LLM/ASR/TTS optionally filtered)。

    vendor_id 为 null 的 provider 落入 ``ungrouped``(eg 单 ASR provider)。
    """
    vendors = await svc.list_vendors()
    providers = await svc.list_providers(type)

    vendor_map: dict[str, list[svc.Provider]] = {v.id: [] for v in vendors}
    ungrouped: list[svc.Provider] = []
    for p in providers:
        if p.vendor_id and p.vendor_id in vendor_map:
            vendor_map[p.vendor_id].append(p)
        else:
            ungrouped.append(p)

    return ProvidersGroupedResponse(
        vendors=[
            VendorGroupOut(
                id=v.id, name=v.name, vendor_kind=v.vendor_kind,
                default_endpoint=v.default_endpoint,
                credential_key_name=v.credential_key_name,
                endpoint_env_name=v.endpoint_env_name,
                has_credential=v.has_credential,
                credential_source=v.credential_source,
                color=v.color, icon=v.icon,
                providers=[_to_provider_out(p) for p in vendor_map[v.id]],
            )
            for v in vendors
            # 只列含该 type provider 的 vendor; 即使空也保留以便前端 add 按钮可见。
        ],
        ungrouped=[_to_provider_out(p) for p in ungrouped],
    )


@router.post("/ai-providers", response_model=ProviderOut, status_code=201)
async def create_provider_endpoint(body: ProviderCreateBody) -> Any:
    if body.type not in ("llm", "asr", "tts"):
        raise HTTPException(
            status_code=400,
            detail="type must be one of llm / asr / tts",
        )
    if body.vendor_id and await svc.get_vendor(body.vendor_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"vendor {body.vendor_id!r} not found",
        )
    p = await svc.create_provider(
        vendor_id=body.vendor_id, type=body.type, name=body.name,
        model=body.model, endpoint=body.endpoint, extra_json=body.extra_json,
    )
    return _to_provider_out(p)


@router.patch("/ai-providers/{provider_id}", response_model=ProviderOut)
async def patch_provider_endpoint(provider_id: int, body: ProviderPatchBody) -> Any:
    p = await svc.patch_provider(
        provider_id,
        name=body.name, model=body.model, endpoint=body.endpoint,
        extra_json=body.extra_json, enabled=body.enabled,
    )
    if p is None:
        raise HTTPException(status_code=404, detail=f"provider {provider_id} not found")
    return _to_provider_out(p)


@router.delete("/ai-providers/{provider_id}", status_code=204)
async def delete_provider_endpoint(provider_id: int) -> None:
    result = await svc.delete_provider(provider_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail=f"provider {provider_id} not found")
    if result == "builtin":
        raise HTTPException(
            status_code=403,
            detail="cannot delete builtin provider; PATCH enabled=false to disable",
        )


@router.post("/ai-providers/{provider_id}/activate", response_model=ProviderOut)
async def activate_provider_endpoint(provider_id: int) -> Any:
    result = await svc.activate_provider(provider_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail=f"provider {provider_id} not found")
    if result == "no_credential":
        raise HTTPException(
            status_code=400,
            detail=(
                "vendor has no credential configured (DB or env); "
                "POST /api/ai-vendors/{vendor_id}/credentials first"
            ),
        )
    p = await svc.get_provider(provider_id)
    assert p is not None
    return _to_provider_out(p)

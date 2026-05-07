"""v3-G chunk 1.7 — Settings REST API（model 切换器）。

目前只暴露 LLM model 切换：

  GET  /api/settings/model
       → {"current": "openai/qwen3.6-plus", "available": [{...}, ...]}

  POST /api/settings/model  body={"model": "openai/qwen3.6-max-preview"}
       → {"status": "ok", "current": "..."}（写回 config.yaml + reload）

校验：``model`` 必须在 ``available_models`` 列表的某个 ``id`` 里，
否则 400。这避免前端自由文本注入随意 model id 触发 LiteLLM 调用失败。

持久化：和 base_instruction 同款——读最新 yaml → 改 default_model 一项 → safe_dump 写回 → reload_config_yaml()。
进程内 ``get_default_model()`` 立即看到新值，下一条消息生效，无需重启。
"""
from pathlib import Path
from typing import Any, List

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import (
    config_yaml,
    get_available_models,
    get_default_model,
    reload_config_yaml,
)

router = APIRouter()

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


class ModelInfo(BaseModel):
    id: str
    display_name: str
    description: str = ""
    tier: str = "stable"   # "stable" | "preview"


class ModelStateResponse(BaseModel):
    current: str
    available: List[ModelInfo]


class ModelUpdateBody(BaseModel):
    model: str


def _coerce_models(raw: list) -> List[ModelInfo]:
    out: List[ModelInfo] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mid = item.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        out.append(ModelInfo(
            id=mid,
            display_name=str(item.get("display_name") or mid),
            description=str(item.get("description") or ""),
            tier=str(item.get("tier") or "stable"),
        ))
    return out


@router.get("/settings/model", response_model=ModelStateResponse)
async def get_model_settings() -> Any:
    return ModelStateResponse(
        current=get_default_model(),
        available=_coerce_models(get_available_models()),
    )


@router.post("/settings/model", response_model=ModelStateResponse)
async def set_model_settings(body: ModelUpdateBody) -> Any:
    valid_ids = {m.id for m in _coerce_models(get_available_models())}
    if body.model not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown model id: {body.model!r}. "
                f"Allowed: {sorted(valid_ids)}"
            ),
        )

    try:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                current: dict = yaml.safe_load(f) or {}
        else:
            current = {}
        current["default_model"] = body.model
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                current,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        reload_config_yaml()
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=500, detail=f"config.yaml syntax error: {exc}"
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"config.yaml write failed: {exc}"
        ) from exc

    return ModelStateResponse(
        current=get_default_model(),
        available=_coerce_models(get_available_models()),
    )

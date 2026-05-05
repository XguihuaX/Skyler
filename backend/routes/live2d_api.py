"""Live2D models REST API.

Mounted at /api in main.py.  Full URL map:
  GET  /api/live2d/models

v3-E2 commit 3a — 让 CharacterPanel UI 拿到一份"当前已 ship 的 Live2D 角色
列表 + pixi 兼容性"，替代之前裸文本框输入。
"""
from fastapi import APIRouter

from backend.services.live2d_scanner import Live2DScanResult, scan_live2d_models

router = APIRouter()


@router.get("/live2d/models")
async def list_live2d_models() -> Live2DScanResult:
    """Return the currently-shipping Live2D character roster.

    扫描 ``frontend/public/live2d/<slug>/``，每条结果带 pixi-live2d-display
    兼容判定 + warnings。单 slug 的解析失败不会让整个 API fail —— 错误以
    ``warnings`` 数组返回，``pixi_compatible=False``。
    """
    return scan_live2d_models()

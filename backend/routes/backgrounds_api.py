"""Backgrounds asset REST API.

Mounted at /api in main.py.  Full URL map:
  GET  /api/backgrounds

v3.5 chunk 5a — CharacterPanel 用本接口拿"当前可用背景资产"下拉，每条带
type=image/video 让前端在 ``<img>`` / ``<video>`` 间分发。
"""
from fastapi import APIRouter

from backend.services.backgrounds_scanner import (
    BackgroundScanResult,
    scan_backgrounds,
)

router = APIRouter()


@router.get("/backgrounds")
async def list_backgrounds() -> BackgroundScanResult:
    """Return the currently-shipping background asset list.

    扫描 ``frontend/public/backgrounds/``（含一层子目录），后缀白名单
    image: jpg / jpeg / png / webp；video: mp4 / webm。其他后缀（README.md /
    .gitkeep / 用户暂存源文件）一律忽略。单文件错误不会让整个 API fail。
    """
    return scan_backgrounds()

"""Health endpoint — exposes model warm-up status.

Mounted at /api in main.py.  Full URL map:
  GET  /api/health
"""
from fastapi import APIRouter

router = APIRouter()

# Module-level mutable state shared with main.py lifespan + ws.py.
# main.py flips these to True as each model finishes loading.
app_state: dict = {
    "embedding_ready": False,
    "whisper_ready": False,
}


@router.get("/health")
async def health() -> dict:
    embedding = "ready" if app_state["embedding_ready"] else "loading"
    whisper = "ready" if app_state["whisper_ready"] else "loading"
    overall = (
        "ready"
        if app_state["embedding_ready"] and app_state["whisper_ready"]
        else "warming"
    )
    return {
        "status": overall,
        "models": {
            "embedding": embedding,
            "whisper": whisper,
            # LiteLLM is lazy — the first call connects. We don't probe here.
            "llm": "ready",
        },
    }

"""momoos.boot — 启动序列耗时插桩(只测、不改启动逻辑)。

用法:
    from backend.utils.boot_tracker import get_tracker
    tracker = get_tracker()
    tracker.start()
    tracker.mark("init_db")
    ...
    tracker.mark_bg("embedding_warm", 6012)   # 背景 warmup 完成时(不进 eager 总时)
    tracker.dump_summary()

snapshot 返回的 dict 给前端 loading 序列吃,渲染真实 boot 行 + warm 行 + total。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("momoos.boot")


class BootTracker:
    def __init__(self) -> None:
        self._t0: Optional[float] = None
        self._last: Optional[float] = None
        self._marks: List[Tuple[str, float]] = []
        self._bg_marks: List[Tuple[str, float]] = []
        self._total_ms: Optional[float] = None
        self._started_wall_iso: Optional[str] = None

    def start(self) -> None:
        now = time.perf_counter()
        self._t0 = now
        self._last = now
        self._marks.clear()
        self._bg_marks.clear()
        self._total_ms = None
        from datetime import datetime, timezone
        self._started_wall_iso = datetime.now(timezone.utc).isoformat()
        logger.info("[boot] === eager sequence start ===")

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        if self._last is None:
            self._t0 = now
            self._last = now
        dur_ms = (now - self._last) * 1000.0
        self._last = now
        self._marks.append((name, dur_ms))
        logger.info("[boot] %s: %.0fms", name, dur_ms)

    def mark_bg(self, name: str, duration_ms: float) -> None:
        """后台 warmup 完成时调 · 不计入 eager 总时 · 进 snapshot 的 bg 列表。"""
        self._bg_marks.append((name, float(duration_ms)))
        logger.info("[boot] bg %s: %.0fms", name, duration_ms)

    def dump_summary(self) -> None:
        if self._t0 is None:
            logger.warning("[boot] dump_summary called before start()")
            return
        self._total_ms = (time.perf_counter() - self._t0) * 1000.0
        logger.info("[boot] ============================================")
        logger.info(
            "[boot] BOOT SUMMARY (eager, %d marks, sorted by duration)",
            len(self._marks),
        )
        logger.info("[boot] ============================================")
        ranked = sorted(self._marks, key=lambda x: x[1], reverse=True)
        for name, dur_ms in ranked:
            pct = (dur_ms / self._total_ms) * 100.0 if self._total_ms > 0 else 0.0
            logger.info("[boot]   %8.1fms  %5.1f%%  %s", dur_ms, pct, name)
        logger.info("[boot] --------------------------------------------")
        logger.info("[boot]   TOTAL (eager, before yield): %.1fms", self._total_ms)
        logger.info("[boot] ============================================")
        logger.info(
            "[boot] (background warmups — embedding / whisper — log their own [TIME])"
        )

    def get_snapshot(self) -> Dict[str, Any]:
        """给 /api/observability/boot-summary · 前端 loading sequence 吃。

        marks: 保留 mark 调用的原始顺序(渲染真实 boot 序列时按顺序 reveal)
        bg:    背景 warmup 完成耗时(embedding / whisper · 单独 panel 显示)
        """
        return {
            "started_at_iso": self._started_wall_iso,
            "marks": [
                {"name": n, "duration_ms": round(d, 1)} for n, d in self._marks
            ],
            "bg": [
                {"name": n, "duration_ms": round(d, 1)} for n, d in self._bg_marks
            ],
            "total_ms": (
                round(self._total_ms, 1) if self._total_ms is not None else None
            ),
        }


_tracker = BootTracker()


def get_tracker() -> BootTracker:
    return _tracker

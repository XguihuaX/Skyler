import logging
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger("momoos.timing")


class Timer:
    def __init__(self) -> None:
        self._start: Optional[float] = None

    def start(self) -> None:
        self._start = time.perf_counter()

    def elapsed(self) -> float:
        if self._start is None:
            return 0.0
        return time.perf_counter() - self._start

    def reset(self) -> None:
        self._start = None


@contextmanager
def timed(label: str) -> Iterator[None]:
    """Log [TIME] {label}: Xms around the wrapped block.

    Works correctly around `await` calls — perf_counter is process-wide and
    the contextmanager only measures wall-clock between __enter__ and __exit__.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000
        logger.info("[TIME] %s: %.0fms", label, ms)

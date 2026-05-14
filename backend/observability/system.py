"""Bugfix-4 — 系统资源采集 (M1 Air 8GB dogfood machine 监控)。

依赖 psutil。如未装 → 字段填 ``None`` (前端表"未知")。

哪些数据
--------
* backend process RSS / CPU%      —— current process psutil.Process()
* 系统总 RAM / 用量 (system-wide)  —— psutil.virtual_memory()
* Disk usage (project dir)         —— psutil.disk_usage
* Whisper model status             —— from backend.asr.whisper.whisper_asr 反射
* Network throughput               —— psutil.net_io_counters() delta

Tauri 主进程内存 / Live2D 估算 —— 不直接从 Python 端跑。**两条策略**:
1. backend 不报 (字段填 None) — Tauri 端可用 Rust ``sysinfo`` crate 在主进程
   自报到前端,本 stage 不实装
2. 前端 sidebar 角落只显示 backend 内存条 (用户拍板) — 足够 dogfood

本模块永不抛:psutil 失败 / 字段缺 → 静默回退 None。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore
    _HAS_PSUTIL = False


# Module-level cache for net_io delta calculation
_last_net: Optional[tuple[float, int, int]] = None  # (timestamp, bytes_recv, bytes_sent)


@dataclass
class SystemResources:
    has_psutil: bool
    # backend process
    backend_rss_mb: Optional[float]
    backend_cpu_percent: Optional[float]
    # system-wide
    system_total_ram_mb: Optional[float]
    system_used_ram_mb: Optional[float]
    system_ram_percent: Optional[float]
    # whisper
    whisper_loaded: bool
    whisper_size: Optional[str]
    whisper_disk_mb: Optional[float]
    # network throughput (KB/s, 取上次调用至本次的 delta)
    net_recv_kbps: Optional[float]
    net_sent_kbps: Optional[float]


_WHISPER_SIZE_DISK_MB = {
    "tiny":   75,
    "base":  142,
    "small": 466,
    "medium": 1500,
    "large-v3": 2900,
}


def _get_whisper_info() -> tuple[bool, Optional[str], Optional[float]]:
    """返回 (loaded, size_label, disk_mb_estimate)。估算 disk 用上面 dict。"""
    try:
        from backend.asr.whisper import whisper_asr
        loaded = whisper_asr._model is not None
        size_label = whisper_asr._loaded_size
        if not size_label:
            from backend.config import get_whisper_model_size
            size_label = get_whisper_model_size()
        disk_mb = _WHISPER_SIZE_DISK_MB.get(size_label) if size_label else None
        return loaded, size_label, disk_mb
    except Exception:
        return False, None, None


def _get_net_throughput() -> tuple[Optional[float], Optional[float]]:
    """psutil net_io 比上次,推 KB/s。第一次调用 → (0, 0)。"""
    global _last_net
    if not _HAS_PSUTIL:
        return None, None
    try:
        counters = psutil.net_io_counters()
        now = time.monotonic()
        if _last_net is None:
            _last_net = (now, counters.bytes_recv, counters.bytes_sent)
            return 0.0, 0.0
        last_ts, last_recv, last_sent = _last_net
        dt = max(now - last_ts, 0.001)  # 防除零
        recv_kbps = (counters.bytes_recv - last_recv) / 1024.0 / dt
        sent_kbps = (counters.bytes_sent - last_sent) / 1024.0 / dt
        _last_net = (now, counters.bytes_recv, counters.bytes_sent)
        return round(max(recv_kbps, 0.0), 1), round(max(sent_kbps, 0.0), 1)
    except Exception:
        return None, None


def collect() -> SystemResources:
    """采集当前系统资源 snapshot。永不抛。"""
    if not _HAS_PSUTIL:
        loaded, size, disk_mb = _get_whisper_info()
        return SystemResources(
            has_psutil=False,
            backend_rss_mb=None,
            backend_cpu_percent=None,
            system_total_ram_mb=None,
            system_used_ram_mb=None,
            system_ram_percent=None,
            whisper_loaded=loaded,
            whisper_size=size,
            whisper_disk_mb=disk_mb,
            net_recv_kbps=None,
            net_sent_kbps=None,
        )
    try:
        proc = psutil.Process(os.getpid())
        rss_mb = proc.memory_info().rss / 1024 / 1024
        # cpu_percent(None) 是非阻塞,会基于上次调用 delta。第一次调用 → 0.0。
        cpu_pct = proc.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        loaded, size, disk_mb = _get_whisper_info()
        recv_kbps, sent_kbps = _get_net_throughput()
        return SystemResources(
            has_psutil=True,
            backend_rss_mb=round(rss_mb, 1),
            backend_cpu_percent=round(cpu_pct, 1),
            system_total_ram_mb=round(vm.total / 1024 / 1024, 0),
            system_used_ram_mb=round(vm.used / 1024 / 1024, 0),
            system_ram_percent=round(vm.percent, 1),
            whisper_loaded=loaded,
            whisper_size=size,
            whisper_disk_mb=disk_mb,
            net_recv_kbps=recv_kbps,
            net_sent_kbps=sent_kbps,
        )
    except Exception as exc:
        logger.warning("[observability.system] psutil collect failed: %s", exc)
        loaded, size, disk_mb = _get_whisper_info()
        return SystemResources(
            has_psutil=False,
            backend_rss_mb=None,
            backend_cpu_percent=None,
            system_total_ram_mb=None,
            system_used_ram_mb=None,
            system_ram_percent=None,
            whisper_loaded=loaded,
            whisper_size=size,
            whisper_disk_mb=disk_mb,
            net_recv_kbps=None,
            net_sent_kbps=None,
        )


def to_dict(s: SystemResources) -> dict:
    return asdict(s)

"""Atomic YAML write helper — shared infra for Stage 2 (MCP form add,
future Live2D / Skill config write paths) + retrofit of legacy config_api
write-backs.

Contract
--------

``await write_config_atomic(path, mutate_fn)`` runs:

  1. Acquire per-path ``asyncio.Lock`` (serialises concurrent writers in
     the same process; cross-process is out of scope — Skyler runs a
     single uvicorn worker).
  2. Read existing YAML into a Python dict (``yaml.safe_load``). Missing
     file → start from empty dict (no FileNotFoundError to caller).
  3. Call ``mutate_fn(data)``. May mutate in-place + return None, or
     return a new dict. The returned-or-mutated dict is what gets dumped.
     ``mutate_fn`` may be sync or async (``inspect.iscoroutinefunction``).
  4. Dump to ``<path>.tmp.<pid>.<counter>`` via ``yaml.safe_dump``
     (allow_unicode=True, sort_keys=False to preserve original ordering
     intent).
  5. ``os.rename`` swap — atomic on POSIX (same-filesystem; we always
     write the tmp file next to the target).
  6. If anything in steps 3-5 raises, the tmp file is removed and the
     original file is untouched (rollback).

Notes
-----

* Lock is per-resolved-path-string; ``/foo/bar.yaml`` and ``/foo/./bar.yaml``
  would not share a lock. Callers should pass ``Path(...).resolve()`` or
  consistent strings if that matters; current callers all pass the same
  ``_CONFIG_PATH`` constant.
* This helper does **not** reload any in-process caches (``backend.config.
  reload_config_yaml`` etc). Caller is responsible — keeps the helper's
  scope narrow.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

import yaml

logger = logging.getLogger(__name__)


# Per-path lock table. Module-level dict keyed by str(path). Locks are
# created lazily; no eviction (config paths are a tiny finite set).
_locks: dict[str, asyncio.Lock] = {}
_locks_dict_lock = asyncio.Lock()

# Per-process counter to disambiguate tmp filenames when two writes for
# the same path happen back-to-back (lock prevents real concurrency but a
# crashed-mid-write tmp from a prior run shouldn't clash either).
_tmp_counter = 0


MutateFn = Callable[[dict], Union[Optional[dict], Awaitable[Optional[dict]]]]


async def _get_lock(path_key: str) -> asyncio.Lock:
    """Lazy per-path lock. Guarded by a meta-lock so two callers don't race
    to create separate Lock objects for the same path."""
    if path_key in _locks:
        return _locks[path_key]
    async with _locks_dict_lock:
        if path_key not in _locks:
            _locks[path_key] = asyncio.Lock()
        return _locks[path_key]


async def write_config_atomic(
    path: Union[str, os.PathLike],
    mutate_fn: MutateFn,
) -> dict:
    """Atomically read-modify-write a YAML config file.

    Args:
        path:      Target YAML file path. Missing file is treated as
                   ``{}`` (no error).
        mutate_fn: Callable receiving the parsed dict. May mutate
                   in-place and return None, or return a new dict to
                   replace contents. Sync or async.

    Returns:
        The dict that was written (post-mutation).

    Raises:
        yaml.YAMLError: existing file is invalid YAML.
        OSError:        filesystem error during read / tmp write / rename.
        Anything raised by ``mutate_fn``: propagated; original file is
        untouched and any tmp file is removed.
    """
    target = Path(path)
    path_key = str(target)
    lock = await _get_lock(path_key)

    async with lock:
        # 1. Load existing (or empty).
        if target.exists():
            with open(target, encoding="utf-8") as f:
                data: dict = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise yaml.YAMLError(
                    f"{target}: top-level YAML is not a mapping "
                    f"(got {type(data).__name__})"
                )
        else:
            data = {}

        # 2. Mutate (sync or async).
        result = mutate_fn(data)
        if inspect.isawaitable(result):
            result = await result
        # mutate_fn returning None ≡ in-place mutation.
        final = result if isinstance(result, dict) else data

        # 3. Write to tmp + rename.
        global _tmp_counter
        _tmp_counter += 1
        tmp = target.with_name(
            f"{target.name}.tmp.{os.getpid()}.{_tmp_counter}"
        )
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    final,
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )
            os.rename(tmp, target)
        except Exception:
            # Best-effort cleanup of dangling tmp; original target
            # untouched because os.rename hasn't happened yet (or failed
            # mid-rename which leaves source as tmp, irrelevant).
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError as cleanup_exc:
                logger.warning(
                    "[yaml_atomic] tmp cleanup failed %s: %s", tmp, cleanup_exc,
                )
            raise

        return final

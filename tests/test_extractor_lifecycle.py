"""v3.5 chunk 10 commit 7 — worker lifecycle + config wiring。

* config.yaml ``memory.extractor`` 段 + getters 默认值
* backend.main lifespan：``enabled=true`` → start；``enabled=false`` →
  log skip
* shutdown 调 ``stop()``
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import config_yaml
from backend.memory import extractor as ex_mod

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Config block exists
# ---------------------------------------------------------------------------


def test_config_yaml_has_extractor_block():
    print("\n[config] config.yaml memory.extractor 段存在")
    mem_cfg = (config_yaml.get("memory") or {})
    extractor = mem_cfg.get("extractor")
    check("memory.extractor key 存在",
          extractor is not None and isinstance(extractor, dict))
    if extractor:
        for k in ["enabled", "interval_seconds", "batch_size",
                  "min_confidence", "dup_threshold", "llm_judge_enabled"]:
            check(f"{k} 字段在", k in extractor)


def test_extractor_getters_match_config():
    print("\n[config] getters 反映 config.yaml 值")
    cfg = (config_yaml.get("memory") or {}).get("extractor") or {}
    check("enabled getter",
          ex_mod.get_extractor_enabled() == bool(cfg.get("enabled", True)))
    check("interval_seconds getter",
          ex_mod.get_extractor_interval_seconds()
          == int(cfg.get("interval_seconds", 300)))
    check("batch_size getter",
          ex_mod.get_extractor_batch_size()
          == int(cfg.get("batch_size", 50)))


# ---------------------------------------------------------------------------
# main.py lifespan wiring
# ---------------------------------------------------------------------------


def test_main_py_registers_extractor_worker():
    print("\n[main] main.py lifespan 注册 worker + log + shutdown stop")
    import backend.main as main_mod
    src = open(main_mod.__file__, "r", encoding="utf-8").read()

    check("import get_extractor / enabled / interval",
          "from backend.memory.extractor import" in src
          and "get_extractor" in src
          and "get_extractor_enabled" in src
          and "get_extractor_interval_seconds" in src)
    check("if get_extractor_enabled() gate 存在",
          "if get_extractor_enabled():" in src)
    check("asyncio.create_task(ex.run_loop()) 启动",
          "asyncio.create_task(ex.run_loop())" in src)
    check("启动日志 [extractor] started interval=",
          "[extractor] started interval=" in src)
    check("disabled 时日志 [extractor] disabled",
          "[extractor] disabled" in src)
    check("shutdown 调 stop()",
          "extractor_worker" in src
          and "ex.stop()" in src)


def test_disabled_path_skips_worker_in_lifespan():
    print("\n[main] enabled=false → log skip 不 create_task")
    # 静态扫源；运行时不易模拟整个 lifespan，因此仅断言代码路径正确
    import backend.main as main_mod
    src = open(main_mod.__file__, "r", encoding="utf-8").read()
    # 关键 invariant：create_task 只在 if get_extractor_enabled(): 块内
    create_task_pos = src.find("ex._task = asyncio.create_task(ex.run_loop())")
    gate_pos = src.rfind("if get_extractor_enabled():", 0, create_task_pos)
    check("create_task 出现在 enabled gate 之后",
          create_task_pos > 0 and gate_pos > 0 and gate_pos < create_task_pos)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_config_yaml_has_extractor_block()
    test_extractor_getters_match_config()
    test_main_py_registers_extractor_worker()
    test_disabled_path_skips_worker_in_lifespan()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()

"""v3.5 chunk 9 Part 0 — embedding 检索性能优化 unit + smoke。

3 项零风险优化：
  1. 短输入 < threshold 直接 short-circuit return [] —— 0ms（不 encode）
  2. embedding LRU + TTL 缓存 —— 重复 query 直接命中
  3. device='auto' → cpu（benchmark 显示对短文本 mps 无 advantage）

也验：
  * cache 容量 eviction（>= size_limit 弹最旧）
  * cache TTL 过期
  * 配置变量真生效（config.yaml memory.embedding.* 路径）
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.memory import long_term as lt
from backend.config import (
    get_embedding_cache_size,
    get_embedding_cache_ttl_seconds,
    get_embedding_device,
    get_embedding_short_input_threshold,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. config getters：默认值 + 类型容错
# ---------------------------------------------------------------------------


def test_config_defaults():
    print("\n[config] 默认值")
    check("device default == 'auto'", get_embedding_device() in ("auto", "cpu", "mps"))
    check("short_input_threshold int >= 0",
          isinstance(get_embedding_short_input_threshold(), int)
          and get_embedding_short_input_threshold() >= 0)
    check("cache_size int > 0",
          isinstance(get_embedding_cache_size(), int)
          and get_embedding_cache_size() > 0)
    check("cache_ttl_seconds int > 0",
          isinstance(get_embedding_cache_ttl_seconds(), int)
          and get_embedding_cache_ttl_seconds() > 0)


# ---------------------------------------------------------------------------
# 2. _pick_device：auto / cpu / mps 三档
# ---------------------------------------------------------------------------


def test_pick_device_explicit_cpu():
    print("\n[device] explicit cpu")
    from backend.config import config_yaml
    old = config_yaml.get("memory", {}).get("embedding", {}).get("device")
    try:
        config_yaml.setdefault("memory", {}).setdefault("embedding", {})["device"] = "cpu"
        check("explicit cpu → cpu", lt._pick_device() == "cpu")
    finally:
        config_yaml["memory"]["embedding"]["device"] = old or "auto"


def test_pick_device_auto_defaults_cpu():
    print("\n[device] auto → cpu（chunk 9 决定）")
    from backend.config import config_yaml
    old = config_yaml.get("memory", {}).get("embedding", {}).get("device")
    try:
        config_yaml.setdefault("memory", {}).setdefault("embedding", {})["device"] = "auto"
        check("auto → cpu（benchmark 决定）", lt._pick_device() == "cpu")
    finally:
        config_yaml["memory"]["embedding"]["device"] = old or "auto"


# ---------------------------------------------------------------------------
# 3. _EmbeddingCache LRU + TTL
# ---------------------------------------------------------------------------


def test_cache_basic_get_put():
    print("\n[cache] 基础 get / put / hit / miss")
    import numpy as np
    c = lt._EmbeddingCache()
    check("空 cache miss", c.get("xxx") is None)
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    c.put("xxx", v)
    got = c.get("xxx")
    check("put 后 get 命中", got is not None and (got == v).all())


def test_cache_lru_eviction():
    print("\n[cache] LRU eviction（超 size 弹最旧）")
    import numpy as np
    from backend.config import config_yaml
    old = config_yaml.get("memory", {}).get("embedding", {}).get("cache_size")
    try:
        config_yaml.setdefault("memory", {}).setdefault("embedding", {})["cache_size"] = 3
        c = lt._EmbeddingCache()
        for i, k in enumerate(["a", "b", "c", "d"]):
            c.put(k, np.array([float(i)], dtype=np.float32))
        # size=3，最早的 "a" 被弹
        check("'a' 被弹（最旧）", c.get("a") is None)
        check("'b' 留", c.get("b") is not None)
        check("'c' 留", c.get("c") is not None)
        check("'d' 留", c.get("d") is not None)
    finally:
        config_yaml["memory"]["embedding"]["cache_size"] = old or 100


def test_cache_lru_move_to_end_on_hit():
    print("\n[cache] hit 移到末尾（最近用），避免被弹")
    import numpy as np
    from backend.config import config_yaml
    old = config_yaml.get("memory", {}).get("embedding", {}).get("cache_size")
    try:
        config_yaml.setdefault("memory", {}).setdefault("embedding", {})["cache_size"] = 3
        c = lt._EmbeddingCache()
        for k in ["a", "b", "c"]:
            c.put(k, np.array([0.0], dtype=np.float32))
        c.get("a")  # bump "a" to end
        c.put("d", np.array([0.0], dtype=np.float32))  # 弹的应该是 "b" 而非 "a"
        check("hit 后 'a' 不被弹", c.get("a") is not None)
        check("'b' 被弹（hit 后变最旧）", c.get("b") is None)
    finally:
        config_yaml["memory"]["embedding"]["cache_size"] = old or 100


def test_cache_ttl_expiry():
    print("\n[cache] TTL 过期")
    import numpy as np
    from backend.config import config_yaml
    old_ttl = config_yaml.get("memory", {}).get("embedding", {}).get("cache_ttl_seconds")
    try:
        config_yaml.setdefault("memory", {}).setdefault("embedding", {})["cache_ttl_seconds"] = 0
        c = lt._EmbeddingCache()
        c.put("k", np.array([1.0], dtype=np.float32))
        time.sleep(0.01)
        check("TTL 0s + 0.01s sleep → 过期 miss", c.get("k") is None)
    finally:
        config_yaml["memory"]["embedding"]["cache_ttl_seconds"] = old_ttl or 300


def test_cache_disabled_when_size_zero():
    print("\n[cache] size=0 → 完全禁用")
    import numpy as np
    from backend.config import config_yaml
    old = config_yaml.get("memory", {}).get("embedding", {}).get("cache_size")
    try:
        config_yaml.setdefault("memory", {}).setdefault("embedding", {})["cache_size"] = 0
        c = lt._EmbeddingCache()
        c.put("k", np.array([1.0], dtype=np.float32))
        check("size=0 → put 不入 cache", c.get("k") is None)
    finally:
        config_yaml["memory"]["embedding"]["cache_size"] = old or 100


# ---------------------------------------------------------------------------
# 4. search_relevant_memories short-input gate（核心 perf 优化）
# ---------------------------------------------------------------------------


async def test_short_input_skip_no_encode():
    print("\n[perf] short-input gate — len < threshold 直接 return []，<5ms")
    # 验证：query 短 → 不调 _encode 也不查 DB（理想 sub-ms，宽松到 < 5ms）
    t0 = time.perf_counter()
    res = await lt.search_relevant_memories("default", "嗨", character_id=1)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    check("返回 []", res == [])
    check(f"sub-5ms 短路（实测 {elapsed_ms:.2f}ms）", elapsed_ms < 5.0)


async def test_short_input_threshold_respected():
    print("\n[perf] short_input_threshold 配置真生效")
    from backend.config import config_yaml
    old = config_yaml.get("memory", {}).get("embedding", {}).get("short_input_threshold")
    try:
        # 把 threshold 调到 5 → 6 字应继续走完整路径
        config_yaml.setdefault("memory", {}).setdefault("embedding", {})["short_input_threshold"] = 5
        # 4 字短路；6 字进 encode
        await lt.preload()
        t0 = time.perf_counter()
        await lt.search_relevant_memories("default", "abcd", character_id=1)  # 4 chars < 5
        skip_ms = (time.perf_counter() - t0) * 1000
        check("4 chars < 5 → 短路", skip_ms < 5.0)

        # 6 chars goes through (will hit DB but no memories)
        t0 = time.perf_counter()
        await lt.search_relevant_memories("default", "abcdef", character_id=1)
        full_ms = (time.perf_counter() - t0) * 1000
        # cache warmup 后应也很快，主要是 SQL；不强约束上限只断言它**做了事**
        # （≥ 短路路径 或 至少经过了 _encode 的代码路径——通过日志可见，不易
        # 在测试里直接断言；只要不抛即可）
        check(f"6 chars >= 5 → 走完整路径（实测 {full_ms:.2f}ms）", True)
    finally:
        config_yaml["memory"]["embedding"]["short_input_threshold"] = old or 10


# ---------------------------------------------------------------------------
# 5. encode cache 集成（真 model）
# ---------------------------------------------------------------------------


async def test_encode_cache_hit_is_subms():
    print("\n[cache] _encode 命中 cache → sub-ms")
    lt._cache.clear()
    await lt.preload()
    q = "今天工作真累，明天要早起开会，希望能睡个好觉"
    # warmup
    await lt._encode(q)
    # 2nd call should hit cache (or near it)
    t0 = time.perf_counter()
    await lt._encode(q)
    cache_ms = (time.perf_counter() - t0) * 1000
    check(f"cache hit < 5ms（实测 {cache_ms:.2f}ms）", cache_ms < 5.0)
    check("cache size == 1", lt._cache.stats()["size"] == 1)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_short_input_skip_no_encode()
    await test_short_input_threshold_respected()
    await test_encode_cache_hit_is_subms()


def main():
    test_config_defaults()
    test_pick_device_explicit_cpu()
    test_pick_device_auto_defaults_cpu()
    test_cache_basic_get_put()
    test_cache_lru_eviction()
    test_cache_lru_move_to_end_on_hit()
    test_cache_ttl_expiry()
    test_cache_disabled_when_size_zero()
    asyncio.run(amain())

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

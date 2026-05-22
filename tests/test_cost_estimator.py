"""INV-9 §7 · cost_estimator + cap check unit/integration test。

覆盖:
  1. estimate_fish_cost_for_text / estimate_fish_cost_for_chars 单元
  2. get_user_cost_caps profile_data JSON 读取 + default fallback
  3. tts_log.estimate_cost fish-path 接 model='s2-pro' byte-based
  4. tts_log.estimate_cost cosyvoice-path backward compat 不破
  5. check_fish_cost_cap_exceeded 集成 test(DB 聚合 + cap 判定)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.cost_estimator import (  # noqa: E402
    DEFAULT_DAILY_CAP_USD,
    DEFAULT_MONTHLY_CAP_USD,
    FISH_S2_PRO_COST_PER_M_BYTES_USD,
    estimate_fish_cost_for_chars,
    estimate_fish_cost_for_text,
    get_user_cost_caps,
)
from backend.observability.tts_log import estimate_cost  # noqa: E402

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ─────────────────────────────────────────────────────────────────────
# 1. estimate_fish_cost_for_text / for_chars
# ─────────────────────────────────────────────────────────────────────
def test_fish_cost_for_text_japanese():
    print("\n[1.1] estimate_fish_cost_for_text · 日语 100 chars")
    # 模拟 INV-8 §1.3.10 stage 2 T5 (181 bytes Mai 日语)
    text = "麻衣はそういう人だから。少しは気を遣ってあげなさい。"
    bytes_real = len(text.encode("utf-8"))
    cost = estimate_fish_cost_for_text(text)
    expected = round(bytes_real / 1_000_000 * 15.0, 6)
    check(f"bytes={bytes_real} cost ≈ ${expected:.6f}",
          abs(cost - expected) < 1e-9, detail=f"got ${cost:.6f}")


def test_fish_cost_for_text_empty():
    print("\n[1.2] estimate_fish_cost_for_text · 空 / None")
    check("'' → 0.0", estimate_fish_cost_for_text("") == 0.0)
    check("None → 0.0", estimate_fish_cost_for_text(None) == 0.0)


def test_fish_cost_for_chars_ja():
    print("\n[1.3] estimate_fish_cost_for_chars · ja 100 char → ~300 bytes")
    cost = estimate_fish_cost_for_chars(100, lang="ja")
    expected = round(100 * 3 / 1_000_000 * 15.0, 6)  # $0.0045
    check(f"100 ja chars → ${expected:.6f}",
          abs(cost - expected) < 1e-9, detail=f"got ${cost:.6f}")


def test_fish_cost_for_chars_en():
    print("\n[1.4] estimate_fish_cost_for_chars · en 1000 char → 1000 bytes")
    cost = estimate_fish_cost_for_chars(1000, lang="en")
    expected = round(1000 * 1 / 1_000_000 * 15.0, 6)  # $0.015
    check(f"1000 en chars → ${expected:.6f}",
          abs(cost - expected) < 1e-9, detail=f"got ${cost:.6f}")


def test_fish_cost_for_chars_zh_same_as_ja():
    print("\n[1.5] estimate_fish_cost_for_chars · zh / ja 同 3 bytes/char")
    c_ja = estimate_fish_cost_for_chars(100, lang="ja")
    c_zh = estimate_fish_cost_for_chars(100, lang="zh")
    check("ja == zh", c_ja == c_zh)


def test_fish_cost_for_chars_invalid_lang():
    print("\n[1.6] estimate_fish_cost_for_chars · 未知 lang → ja 兜底")
    cost = estimate_fish_cost_for_chars(100, lang="xx")
    expected = estimate_fish_cost_for_chars(100, lang="ja")
    check("unknown lang fallback ja", cost == expected)


def test_fish_cost_for_chars_zero():
    print("\n[1.7] estimate_fish_cost_for_chars · 0 chars → 0")
    check("0 → 0.0", estimate_fish_cost_for_chars(0) == 0.0)
    check("-1 → 0.0", estimate_fish_cost_for_chars(-1) == 0.0)


# ─────────────────────────────────────────────────────────────────────
# 2. get_user_cost_caps · profile_data JSON 读取
# ─────────────────────────────────────────────────────────────────────
def test_get_caps_default():
    print("\n[2.1] get_user_cost_caps · None profile_data → defaults")
    d, m = get_user_cost_caps(None)
    check(f"daily == {DEFAULT_DAILY_CAP_USD}", d == DEFAULT_DAILY_CAP_USD)
    check(f"monthly == {DEFAULT_MONTHLY_CAP_USD}", m == DEFAULT_MONTHLY_CAP_USD)


def test_get_caps_empty_dict():
    print("\n[2.2] get_user_cost_caps · 空 dict → defaults")
    d, m = get_user_cost_caps({})
    check("daily == default", d == DEFAULT_DAILY_CAP_USD)
    check("monthly == default", m == DEFAULT_MONTHLY_CAP_USD)


def test_get_caps_explicit():
    print("\n[2.3] get_user_cost_caps · 显式 daily/monthly")
    pd = {"fish_daily_cost_cap_usd": 0.5, "fish_monthly_cost_cap_usd": 10.0}
    d, m = get_user_cost_caps(pd)
    check("daily == 0.5", d == 0.5)
    check("monthly == 10.0", m == 10.0)


def test_get_caps_partial():
    print("\n[2.4] get_user_cost_caps · 只设 daily")
    pd = {"fish_daily_cost_cap_usd": 2.0}
    d, m = get_user_cost_caps(pd)
    check("daily == 2.0", d == 2.0)
    check("monthly fallback default", m == DEFAULT_MONTHLY_CAP_USD)


def test_get_caps_invalid_values():
    print("\n[2.5] get_user_cost_caps · 无效值 fallback default")
    pd = {"fish_daily_cost_cap_usd": "abc", "fish_monthly_cost_cap_usd": None}
    d, m = get_user_cost_caps(pd)
    check("daily 无效 → default", d == DEFAULT_DAILY_CAP_USD)
    check("monthly None → default", m == DEFAULT_MONTHLY_CAP_USD)


def test_get_caps_non_dict():
    print("\n[2.6] get_user_cost_caps · 非 dict 返 default")
    d, m = get_user_cost_caps([1, 2, 3])  # type: ignore
    check("list 返 default", d == DEFAULT_DAILY_CAP_USD)


# ─────────────────────────────────────────────────────────────────────
# 3. tts_log.estimate_cost · fish-path byte-based
# ─────────────────────────────────────────────────────────────────────
def test_estimate_cost_s2pro_with_raw_text():
    print("\n[3.1] estimate_cost · model='s2-pro' + raw_text → byte-based")
    text = "麻衣はそういう人だから。"
    bytes_real = len(text.encode("utf-8"))
    cost = estimate_cost(input_chars=len(text), model="s2-pro", raw_text=text)
    expected = round(bytes_real / 1_000_000 * 15.0, 6)
    check(f"$ {expected:.6f}", abs(cost - expected) < 1e-9)


def test_estimate_cost_s2pro_chars_fallback():
    print("\n[3.2] estimate_cost · model='s2-pro' 无 raw_text → chars × 3 估算")
    cost = estimate_cost(input_chars=100, model="s2-pro")
    expected = round(100 * 3 / 1_000_000 * 15.0, 6)
    check(f"100 chars → ${expected:.6f}", abs(cost - expected) < 1e-9)


def test_estimate_cost_s1_model():
    print("\n[3.3] estimate_cost · model='s1' (fish family) byte-based")
    cost = estimate_cost(input_chars=50, model="s1", raw_text="hello")
    bytes_real = len("hello".encode("utf-8"))
    expected = round(bytes_real / 1_000_000 * 15.0, 6)
    check("s1 model fish-path", abs(cost - expected) < 1e-9)


def test_estimate_cost_cosyvoice_backward_compat():
    print("\n[3.4] estimate_cost · cosyvoice 模型 per-char rate 不变")
    # cosyvoice-v3-flash: 0.00007 ¥/char
    cost = estimate_cost(input_chars=100, model="cosyvoice-v3-flash")
    expected = round(100 * 0.00007, 4)  # 0.007
    check(f"cosyvoice-v3-flash → ¥{expected}", abs(cost - expected) < 1e-9)


def test_estimate_cost_unknown_model_fallback():
    print("\n[3.5] estimate_cost · 未知 model fallback per-char")
    cost = estimate_cost(input_chars=100, model="unknown-model")
    expected = round(100 * 0.0007, 4)  # _COST_FALLBACK
    check(f"unknown → fallback ¥{expected}", abs(cost - expected) < 1e-9)


# ─────────────────────────────────────────────────────────────────────
# 4. 集成 test · check_fish_cost_cap_exceeded · DB 聚合
# ─────────────────────────────────────────────────────────────────────
async def _integration_cap_check():
    """模拟用户 profile_data + 历史 tts_call_log 跑 cap check 端到端。"""
    from backend.utils.cost_estimator import check_fish_cost_cap_exceeded
    from backend.database import engine as db_engine
    from sqlalchemy import text as sql_text

    # 清空当日 fish call(避免 prior test pollution)
    async with db_engine.begin() as conn:
        await conn.execute(sql_text("""
            DELETE FROM tts_call_log WHERE source = 'TEST_cap_check_inv9'
        """))

    # 插入 1 笔模拟 fish call · 微 cost(0.001 USD)
    async with db_engine.begin() as conn:
        await conn.execute(sql_text("""
            INSERT INTO tts_call_log
                (source, character_id, voice, model, input_chars,
                 input_preview, cost_estimate, success)
            VALUES ('TEST_cap_check_inv9', 101, 'mai5min_0033', 's2-pro',
                    100, 'test', 0.001, 1)
        """))

    # check user 'default' · profile_data 缺则用 default cap $1/day
    status = await check_fish_cost_cap_exceeded("default")
    print(f"  status: {json.dumps({k: str(v) for k, v in status.items()}, ensure_ascii=False)}")

    # 默认 cap $1.0 + today_cost 应包含 0.001(INSERT 的) + 历史 fish call
    check("status 含 exceeded key", "exceeded" in status)
    check("status 含 today_cost key", "today_cost" in status)
    check("status 含 daily_cap key", "daily_cap" in status)
    check("status['daily_cap'] >= 1.0(default 或更大)",
          status["daily_cap"] >= 1.0)
    check("status['today_cost'] >= 0.001(含 INSERT)",
          status["today_cost"] >= 0.001)
    # 默认 $1/day 下,只要总 cost <$1 就不触发
    if status["today_cost"] < status["daily_cap"]:
        check("today_cost < daily_cap → not exceeded",
              status["exceeded"] is False)

    # 清理 test row
    async with db_engine.begin() as conn:
        await conn.execute(sql_text("""
            DELETE FROM tts_call_log WHERE source = 'TEST_cap_check_inv9'
        """))


def test_integration_cap_check():
    print("\n[4] 集成 · check_fish_cost_cap_exceeded(DB 聚合 + default cap)")
    asyncio.run(_integration_cap_check())


# ─────────────────────────────────────────────────────────────────────
# 5. 集成 test · cap 触发模拟(profile_data daily_cap=0.0001 强制触发)
# ─────────────────────────────────────────────────────────────────────
async def _integration_cap_trigger():
    """profile_data daily_cap 设极低 → 触达 daily cap → exceeded=True。"""
    from backend.utils.cost_estimator import check_fish_cost_cap_exceeded
    from backend.database import engine as db_engine
    from backend.database.models import User
    from sqlalchemy import select, update

    # 清空 + 插入 1 笔 cost=0.01 (远超 0.0001 cap)
    async with db_engine.begin() as conn:
        from sqlalchemy import text as sql_text
        await conn.execute(sql_text("""
            DELETE FROM tts_call_log WHERE source = 'TEST_cap_trigger_inv9'
        """))
        await conn.execute(sql_text("""
            INSERT INTO tts_call_log
                (source, character_id, voice, model, input_chars,
                 input_preview, cost_estimate, success)
            VALUES ('TEST_cap_trigger_inv9', 101, 'mai5min_0033', 's2-pro',
                    1000, 'test long', 0.01, 1)
        """))

    # 临时 patch default user profile_data 加 daily_cap=0.0001
    from backend.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        u = (await session.execute(select(User).where(User.user_id == "default"))).scalar_one_or_none()
        if u is None:
            print("  [skip] default user not in DB,集成 test 跳过")
            return
        old_profile = u.profile_data
        try:
            new_profile = json.loads(old_profile) if old_profile else {}
        except (json.JSONDecodeError, TypeError):
            new_profile = {}
        new_profile["fish_daily_cost_cap_usd"] = 0.0001  # 极低
        u.profile_data = json.dumps(new_profile)
        await session.commit()

    try:
        status = await check_fish_cost_cap_exceeded("default")
        print(f"  status: exceeded={status['exceeded']} reason={status['reason']} "
              f"today=${status['today_cost']:.6f} cap=${status['daily_cap']}")
        check("daily_cap == 0.0001(profile_data 覆盖)",
              abs(status["daily_cap"] - 0.0001) < 1e-9)
        check("exceeded == True(today 远超 cap)",
              status["exceeded"] is True)
        check("reason == 'daily'",
              status["reason"] == "daily")
    finally:
        # restore profile_data + 清理 test row
        async with AsyncSessionLocal() as session:
            u = (await session.execute(select(User).where(User.user_id == "default"))).scalar_one_or_none()
            if u is not None:
                u.profile_data = old_profile
                await session.commit()
        async with db_engine.begin() as conn:
            from sqlalchemy import text as sql_text
            await conn.execute(sql_text("""
                DELETE FROM tts_call_log WHERE source = 'TEST_cap_trigger_inv9'
            """))


def test_integration_cap_trigger():
    print("\n[5] 集成 · cap 触发模拟(profile_data daily_cap=0.0001 强制触发)")
    asyncio.run(_integration_cap_trigger())


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────
def main():
    test_fish_cost_for_text_japanese()
    test_fish_cost_for_text_empty()
    test_fish_cost_for_chars_ja()
    test_fish_cost_for_chars_en()
    test_fish_cost_for_chars_zh_same_as_ja()
    test_fish_cost_for_chars_invalid_lang()
    test_fish_cost_for_chars_zero()
    test_get_caps_default()
    test_get_caps_empty_dict()
    test_get_caps_explicit()
    test_get_caps_partial()
    test_get_caps_invalid_values()
    test_get_caps_non_dict()
    test_estimate_cost_s2pro_with_raw_text()
    test_estimate_cost_s2pro_chars_fallback()
    test_estimate_cost_s1_model()
    test_estimate_cost_cosyvoice_backward_compat()
    test_estimate_cost_unknown_model_fallback()
    test_integration_cap_check()
    test_integration_cap_trigger()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()

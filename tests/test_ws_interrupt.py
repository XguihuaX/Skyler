"""Unit tests for v3-F #4 voice interrupt path.

测试覆盖：
  1. ``_request_interrupt`` 同步取消 current_turn + 所有 pending TTS task
  2. ``_save_interrupted_turn`` 把 partial reply 落 chat_history 且 assistant
     行的 ``interrupted_at`` 非空；空回复时只保留 user 行
  3. ``_handle_message_safe`` 收到 cancel 后会调用 _save_interrupted_turn 并
     发送 ``{"type":"done","interrupted":true}``，不会异常断开
  4. 打断不调用 profile_summary 重生成（被打断的轮不代表用户画像）

不覆盖（留给手动验证）：完整 ChatAgent stream + LLM 集成、前端 VAD 触发
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 切到内存 DB，避免污染 dev 库
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Patch DB before importing anything that uses sessions
from backend.database import Base
import backend.database as _db_module

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TEST_SESSION = sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)
_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION

# 注册 ORM 模型；ws 模块会从 _db_module 拉 AsyncSessionLocal，这时它已是 TEST_SESSION
from backend.database import models  # noqa: F401
from backend.database.services import create_user, add_chat_history
from backend.database.models import ChatHistory

import backend.routes.ws as _ws_module
# 双保险：若 ws 此前被其他模块以引用形式加载过，强制覆盖局部绑定
_ws_module.AsyncSessionLocal = TEST_SESSION

from backend.routes.ws import (
    _TurnState, _request_interrupt, _save_interrupted_turn,
    _handle_message_safe,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

USER_ID = "interrupt_test_user"


async def setup_db() -> None:
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TEST_SESSION() as s:
        await create_user(s, USER_ID, "Tester")
    # 跑一次迁移确认幂等也接进了内存 DB —— 内存 DB 已经由 ORM 建表带了列，
    # 这里只是验证迁移函数对已存在表的 idempotency
    from backend.database.migrations.v3_f import run_migration

    # migration 用 _db_module.engine —— 已被 patch 到内存
    await run_migration()


async def _all_chat_rows() -> list:
    async with TEST_SESSION() as s:
        rows = (await s.execute(
            select(ChatHistory).where(ChatHistory.user_id == USER_ID)
            .order_by(ChatHistory.id)
        )).scalars().all()
        return list(rows)


async def _wipe_chat() -> None:
    async with TEST_SESSION() as s:
        rows = (await s.execute(
            select(ChatHistory).where(ChatHistory.user_id == USER_ID)
        )).scalars().all()
        for r in rows:
            await s.delete(r)
        await s.commit()


# ---------------------------------------------------------------------------
# 1. _request_interrupt cancels current_turn + pending_tts
# ---------------------------------------------------------------------------

async def test_request_interrupt_cancels_turn_and_tts():
    print("\n[_request_interrupt — cancels current_turn + pending_tts]")
    state = _TurnState()

    # 模拟一个正在运行的 turn task（不会自然完成）
    async def long_turn():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return "cancelled"
        return "completed"

    state.current_turn = asyncio.create_task(long_turn())

    # 模拟 3 个 pending TTS task
    async def long_synth():
        await asyncio.sleep(10)
        return b"AUDIO"

    state.pending_tts = [asyncio.create_task(long_synth()) for _ in range(3)]

    # 让 event loop 跑一圈，确保 task 已挂起
    await asyncio.sleep(0)

    _request_interrupt(state)

    # 给 cancellation 一点时间生效
    await asyncio.sleep(0.05)

    check("current_turn cancelled",
          state.current_turn.cancelled() or state.current_turn.done())
    check("all pending_tts cancelled",
          all(t.cancelled() or t.done() for t in state.pending_tts))
    check("state.interrupted = True", state.interrupted is True)


async def test_request_interrupt_idempotent_when_no_turn():
    print("\n[_request_interrupt — 没有 in-flight turn 时不抛异常]")
    state = _TurnState()
    # current_turn / pending_tts 都为空
    try:
        _request_interrupt(state)
        check("safe to call with no turn", True)
    except Exception as exc:
        check(f"safe to call with no turn (got {exc!r})", False)


async def test_request_interrupt_skips_done_tasks():
    print("\n[_request_interrupt — done task 不重复 cancel]")
    state = _TurnState()

    async def quick():
        return 1

    done_task = asyncio.create_task(quick())
    await done_task  # let it complete

    state.pending_tts = [done_task]
    state.current_turn = done_task  # also "done"

    # Should not raise
    _request_interrupt(state)
    check("no exception when tasks already done", True)


# ---------------------------------------------------------------------------
# 2. _save_interrupted_turn writes assistant with interrupted_at
# ---------------------------------------------------------------------------

async def test_save_interrupted_writes_assistant_with_timestamp():
    print("\n[_save_interrupted_turn — assistant 行 interrupted_at 非空]")
    await _wipe_chat()
    state = _TurnState()
    state.user_text = "你好"
    state.reply_parts = ["你好呀！", "今天天气真好。"]
    state.user_history_already_written = False
    state.conv_id = None
    state.char_id = None

    await _save_interrupted_turn(state, USER_ID)

    rows = await _all_chat_rows()
    check("2 rows written (user + assistant)", len(rows) == 2)
    if len(rows) >= 2:
        user_row, asst_row = rows[0], rows[1]
        check("first row is user", user_row.role == "user")
        check("first row content == user_text",
              user_row.content == "你好")
        check("user row has no interrupted_at",
              user_row.interrupted_at is None)
        check("second row is assistant",
              asst_row.role == "assistant")
        check("assistant row content == joined reply_parts",
              asst_row.content == "你好呀！今天天气真好。")
        check("assistant row interrupted_at NOT NULL",
              asst_row.interrupted_at is not None)


async def test_save_interrupted_skips_user_when_already_written():
    print("\n[_save_interrupted_turn — skip_user_history=True 不重复写 user]")
    await _wipe_chat()

    # 模拟：ASR 路径已经写了 user 行
    async with TEST_SESSION() as s:
        await add_chat_history(
            s, USER_ID, "user", "已存在的 user 行 (来自 ASR)",
            conversation_id=None, character_id=None,
        )

    state = _TurnState()
    state.user_text = "已存在的 user 行 (来自 ASR)"
    state.reply_parts = ["半截回复"]
    state.user_history_already_written = True

    await _save_interrupted_turn(state, USER_ID)

    rows = await _all_chat_rows()
    user_rows = [r for r in rows if r.role == "user"]
    asst_rows = [r for r in rows if r.role == "assistant"]
    check("only 1 user row (no duplicate)", len(user_rows) == 1)
    check("1 assistant row written", len(asst_rows) == 1)
    if asst_rows:
        check("assistant row interrupted_at non-null",
              asst_rows[0].interrupted_at is not None)


async def test_save_interrupted_with_empty_reply():
    print("\n[_save_interrupted_turn — 空 reply 不写 assistant 行]")
    await _wipe_chat()
    state = _TurnState()
    state.user_text = "在吗"
    state.reply_parts = []  # 用户在 LLM 还没出第一字时打断
    state.user_history_already_written = False

    await _save_interrupted_turn(state, USER_ID)

    rows = await _all_chat_rows()
    check("1 row only (user)", len(rows) == 1)
    if rows:
        check("the row is user", rows[0].role == "user")


async def test_save_interrupted_no_user_text_noop():
    print("\n[_save_interrupted_turn — 没 user_text 时直接 return]")
    await _wipe_chat()
    state = _TurnState()
    # state.user_text 默认 ""

    await _save_interrupted_turn(state, USER_ID)

    rows = await _all_chat_rows()
    check("nothing written", len(rows) == 0)


# ---------------------------------------------------------------------------
# 3. _handle_message_safe interrupt path
# ---------------------------------------------------------------------------

class _FakeWS:
    """记录 send_json / send_bytes 调用的最小 WebSocket stub。"""

    def __init__(self) -> None:
        self.sent: list = []
        self.closed: bool = False

    async def send_json(self, msg: dict) -> None:
        if self.closed:
            raise RuntimeError("ws closed")
        self.sent.append(msg)


async def test_handle_message_safe_interrupt_sends_done_interrupted():
    """模拟一个长跑的 _handle_message：external task.cancel() → safe 收尾。"""
    print("\n[_handle_message_safe — cancel 后发 done.interrupted=true]")
    await _wipe_chat()

    fake_ws = _FakeWS()
    state = _TurnState()
    state.user_text = "在吗"
    state.reply_parts = ["半截"]
    state.conv_id = None
    state.char_id = None

    # mock _handle_message：模拟 LLM 流过程，被 cancel 时抛 CancelledError
    async def fake_handle_message(ws, data, st):
        try:
            await asyncio.sleep(10)  # 永远不会自然完成
        except asyncio.CancelledError:
            raise

    # patch
    original = _ws_module._handle_message
    _ws_module._handle_message = fake_handle_message
    try:
        task = asyncio.create_task(
            _handle_message_safe(fake_ws, {}, state, USER_ID)
        )
        state.current_turn = task
        await asyncio.sleep(0)  # let task start
        task.cancel()
        await task  # safe 不应抛 —— 它把 CancelledError 转成 done.interrupted

        check("task finished cleanly (no exception)", task.done() and not task.exception())
        # 找 done 帧
        done_frames = [m for m in fake_ws.sent if m.get("type") == "done"]
        check("sent exactly 1 done frame", len(done_frames) == 1)
        if done_frames:
            check("done.interrupted = true",
                  done_frames[0].get("interrupted") is True)

        # DB：assistant 行写了 interrupted_at
        rows = await _all_chat_rows()
        asst = [r for r in rows if r.role == "assistant"]
        check("assistant partial reply persisted", len(asst) == 1)
        if asst:
            check("assistant interrupted_at set",
                  asst[0].interrupted_at is not None)
    finally:
        _ws_module._handle_message = original


async def test_handle_message_safe_normal_completion():
    """正常完成（无 cancel）也走 safe 包装，不应有 interrupted 行为。"""
    print("\n[_handle_message_safe — 正常完成不发 interrupted]")
    await _wipe_chat()

    fake_ws = _FakeWS()
    state = _TurnState()
    state.user_text = "你好"

    async def fake_handle_message(ws, data, st):
        # 正常完成：往 ws 发 done，handler 返回
        await ws.send_json({"type": "done"})

    original = _ws_module._handle_message
    _ws_module._handle_message = fake_handle_message
    try:
        await _handle_message_safe(fake_ws, {}, state, USER_ID)
        done_frames = [m for m in fake_ws.sent if m.get("type") == "done"]
        check("1 done frame", len(done_frames) == 1)
        if done_frames:
            check("normal done has no interrupted flag",
                  done_frames[0].get("interrupted") is None)
        rows = await _all_chat_rows()
        check("no chat_history row written by safe (normal path delegates)",
              len(rows) == 0)
    finally:
        _ws_module._handle_message = original


# ---------------------------------------------------------------------------
# 4. interrupt does NOT bump profile_summary counter
# ---------------------------------------------------------------------------

async def test_interrupt_does_not_bump_profile_counter():
    print("\n[_save_interrupted_turn — 不调 _bump_turn_and_maybe_regenerate]")
    await _wipe_chat()
    # 直接观察 turn_count_per_user dict —— 打断不应改变它
    _ws_module.turn_count_per_user[USER_ID] = 0
    state = _TurnState()
    state.user_text = "x"
    state.reply_parts = ["y"]

    await _save_interrupted_turn(state, USER_ID)

    check("turn_count_per_user unchanged after interrupt",
          _ws_module.turn_count_per_user.get(USER_ID, 0) == 0)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main() -> None:
    await setup_db()

    await test_request_interrupt_cancels_turn_and_tts()
    await test_request_interrupt_idempotent_when_no_turn()
    await test_request_interrupt_skips_done_tasks()

    await test_save_interrupted_writes_assistant_with_timestamp()
    await test_save_interrupted_skips_user_when_already_written()
    await test_save_interrupted_with_empty_reply()
    await test_save_interrupted_no_user_text_noop()

    await test_handle_message_safe_interrupt_sends_done_interrupted()
    await test_handle_message_safe_normal_completion()

    await test_interrupt_does_not_bump_profile_counter()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())

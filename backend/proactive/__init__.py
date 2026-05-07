"""v3-G chunk 2 — 通用 proactive engine.

trigger → aggregate → ChatAgent → WS push 流水线。``ProactiveTrigger`` 抽象
让未来 v3-F' 加饭点 / 睡前 / 长闲只是新建一个 trigger 文件 —— engine 本身
trigger-agnostic。

公开 API::

    from backend.proactive import ProactiveTrigger, run_trigger
    from backend.proactive.triggers.morning_briefing import MorningBriefingTrigger

    await run_trigger(MorningBriefingTrigger(), user_id="default")
"""
from backend.proactive.engine import ProactiveTrigger, run_trigger

__all__ = ["ProactiveTrigger", "run_trigger"]

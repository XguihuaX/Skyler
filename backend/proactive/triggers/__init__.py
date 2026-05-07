"""v3-G chunk 2 — proactive trigger 实现集合.

每个 trigger 是一个文件。引入新 trigger：

    from backend.proactive.triggers.morning_briefing import MorningBriefingTrigger

    cron_scheduler.schedule_cron(
        trigger.name, trigger.cron_expr,
        run_trigger, trigger=trigger, user_id="default",
    )
"""

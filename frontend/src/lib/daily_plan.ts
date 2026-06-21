// DailyAgent Stage1-viz · 角色今日日程读取
//
// 后端配对:backend/routes/character_state_api.py
//   GET /api/characters/{id}/daily_plan/today
//
// plan 字段语义:
//   - null  → 今日 row 未生成(cron 5 0 还没跑过 / backfill 跳过 / 全失败)
//   - 数组  → Stage 1 schema 保证非空(_validate_plan_slots 整 plan reject)

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface TodayPlanSlot {
  start: string;      // "HH:MM" 24h
  end: string;        // "HH:MM" 24h(end<start 表跨午夜睡眠块)
  activity: string;   // ≤ 60 字
}

export interface TodayPlan {
  character_id: number;
  date: string;                          // "YYYY-MM-DD" 本地日期 (scheduler tz)
  weekday: string;                       // "周日"
  now_local: string;                     // "HH:MM" 本地时间
  current_slot: TodayPlanSlot | null;    // null = 空档 / plan 缺失
  plan: TodayPlanSlot[] | null;          // null = 今日未生成
}

export async function fetchTodayPlan(characterId: number): Promise<TodayPlan> {
  const res = await fetch(
    `${BACKEND_BASE}/api/characters/${characterId}/daily_plan/today`,
  );
  if (!res.ok) throw new Error(`fetch today daily_plan failed: ${res.status}`);
  return (await res.json()) as TodayPlan;
}

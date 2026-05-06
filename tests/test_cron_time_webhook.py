"""Tests for v3-G chunk 0 — cron scheduler + Time capability + n8n webhook."""
import asyncio
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set webhook secrets BEFORE importing routes (env-driven _get_secret evaluates lazily,
# but we want a stable canonical value for the test).
os.environ.setdefault("N8N_BEARER_TOKEN", "test-bearer-secret")
os.environ.setdefault("N8N_HMAC_SECRET", "test-hmac-secret")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.scheduler import cron as cron_module
from backend.capabilities import CapabilityRegistry
import backend.capabilities.time_capability  # noqa: F401  trigger register
from backend.routes.webhooks_api import router as webhooks_router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. cron scheduler — schedule + list + cancel
# ---------------------------------------------------------------------------

async def test_cron_schedule_and_cancel():
    print("\n[cron — schedule / list / cancel]")
    # 起 scheduler
    await cron_module.start()
    check("scheduler running", cron_module.cron_scheduler.running)

    fired = asyncio.Event()

    async def my_task():
        fired.set()

    # interval 1s 注册
    cron_module.schedule_interval("test_interval", seconds=1, func=my_task)
    jobs = cron_module.list_jobs()
    job_ids = {j["id"] for j in jobs}
    check("interval job listed", "test_interval" in job_ids)

    # 重复抛错
    raised = False
    try:
        cron_module.schedule_interval("test_interval", seconds=2, func=my_task)
    except ValueError:
        raised = True
    check("duplicate interval raises", raised)

    # 等待至多 3s 看到触发
    try:
        await asyncio.wait_for(fired.wait(), timeout=3.0)
        check("interval job fired", True)
    except asyncio.TimeoutError:
        check("interval job fired", False, "did not fire within 3s")

    # cancel
    ok = cron_module.cancel_job("test_interval")
    check("cancel returns True", ok)
    check("cancel non-existent returns False", cron_module.cancel_job("test_interval") is False)

    # cron_expr 形态注册
    cron_module.schedule_cron("test_cron", "0 0 * * *", func=my_task)
    jobs2 = cron_module.list_jobs()
    check("cron job listed", any(j["id"] == "test_cron" for j in jobs2))
    cron_module.cancel_job("test_cron")

    # shutdown 只验证不抛错。APScheduler 3.x 的 shutdown(wait=False) 是
    # 异步排队 —— ``running`` 属性不会立刻翻 False，所以不检查。
    await cron_module.shutdown()


# ---------------------------------------------------------------------------
# 2. Time capability
# ---------------------------------------------------------------------------

async def test_time_capability():
    print("\n[capabilities.time.now]")
    cap = CapabilityRegistry().get("time.now")
    check("time.now registered", cap is not None)
    if cap is None:
        return

    # ChatAgent 调用形态：handler 必须接受 user_id kwarg
    result = await cap.handler(user_id="u1")
    check("returns iso", isinstance(result.get("iso"), str) and "T" in result["iso"])
    check("returns timezone", isinstance(result.get("timezone"), str))
    check("returns human (yyyy-mm-dd)", isinstance(result.get("human"), str)
          and len(result["human"]) >= 19)
    check("weekday in 周一..周日", result.get("weekday") in {"周一","周二","周三","周四","周五","周六","周日"})
    check("is_weekend is bool", isinstance(result.get("is_weekend"), bool))

    # health_check
    health = await CapabilityRegistry().health_check_one("time.now")
    check("time health is healthy", health.get("status") == "healthy")


# ---------------------------------------------------------------------------
# 3. n8n webhook — auth + dispatch
# ---------------------------------------------------------------------------

def _signed_request(client: TestClient, trigger: str, body: dict, *,
                    bearer: str | None = None, secret: str | None = None,
                    bad_signature: bool = False):
    raw = json.dumps(body).encode("utf-8")
    sec = secret if secret is not None else os.environ["N8N_HMAC_SECRET"]
    sig = hmac.new(sec.encode(), raw, hashlib.sha256).hexdigest()
    if bad_signature:
        sig = "0" * 64
    headers = {
        "Authorization": f"Bearer {bearer if bearer is not None else os.environ['N8N_BEARER_TOKEN']}",
        "X-Signature": sig,
        "Content-Type": "application/json",
    }
    return client.post(
        f"/api/webhooks/n8n/{trigger}",
        content=raw,
        headers=headers,
    )


async def test_n8n_webhook():
    print("\n[webhooks.n8n]")

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api")
    client = TestClient(app)

    # 正确签名 + 已知 trigger → 202 ack
    r = _signed_request(client, "test", {"text": "hello"})
    check("valid request returns 200", r.status_code == 200, f"got {r.status_code} body={r.text[:120]}")
    check("response status accepted", r.json().get("status") == "accepted")

    # 错的 bearer
    r = _signed_request(client, "test", {"text": "x"}, bearer="wrong")
    check("bad bearer → 401", r.status_code == 401)

    # 错的 HMAC
    r = _signed_request(client, "test", {"text": "x"}, bad_signature=True)
    check("bad signature → 401", r.status_code == 401)

    # 未知 trigger（先过完认证）
    r = _signed_request(client, "no_such_trigger", {"text": "x"})
    check("unknown trigger → 404", r.status_code == 404)

    # 非 JSON object payload（数组）
    raw = json.dumps([1, 2, 3]).encode()
    sig = hmac.new(os.environ["N8N_HMAC_SECRET"].encode(), raw, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/webhooks/n8n/test",
        content=raw,
        headers={
            "Authorization": f"Bearer {os.environ['N8N_BEARER_TOKEN']}",
            "X-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    check("non-object payload → 400", r.status_code == 400)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_cron_schedule_and_cancel()
    await test_time_capability()
    await test_n8n_webhook()

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
    asyncio.run(main())

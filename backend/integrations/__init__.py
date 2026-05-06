"""External integration clients (OAuth, third-party API wrappers).

跟 ``backend/capabilities/`` 区分：

* ``backend/integrations/`` —— **底层**：负责认证、网络重试、连接复用、健康检
  查。**不暴露 capability**（不带 ``@register_capability`` 装饰器），不进入
  Capability Registry / ToolRegistry。
* ``backend/capabilities/`` —— **上层**：调底层 client 形成给 ChatAgent /
  Scheduler / Webhook 三个 consumer 用的 capability。

第一次接入：``google_calendar``（v3-G chunk 1 起）。后续 网易云 / Bilibili /
Pollinations 都走同样的两层分离。
"""

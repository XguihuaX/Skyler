# 小红书 URL 解析（v3.5 chunk 6c）

Skyler 提供**唯一**一个小红书 capability：``xhs.parse_url(url)``。

## 工程红线 ⚠️

**Skyler 不主动爬小红书。** 工程层面无主动搜索 / 推荐流 / 账号自动化的
代码路径。

| ✅ 做 | ❌ 坚决不做 |
|---|---|
| 用户主动贴 URL → 解析 title / text / images | 主动搜索关键词 / 帮我搜 |
| follow xhslink 短链重定向 | 拉首页推荐 / 关注流 |
| 提取 og:meta 和 ``__INITIAL_STATE__`` JSON | 抓评论 |
| 单次低频被动请求 | 账号登录 / 自动点赞收藏 |
| | 弹幕 / 私信发送 |
| | 批量爬虫 / 高频请求 |

### 为何这条线

* 反爬礼仪：小红书 anti-bot 检测主动爬虫强，挑战 vs 收益不平衡
* 法律 / 合规：批量爬数据涉及用户隐私 + 平台 ToS
* 设计哲学：Skyler 是个人陪伴助手，不是数据采集工具

## 使用

无需配置。**用户场景**：

* "帮我看看这条小红书 → URL" → Skyler 调 ``xhs.parse_url`` → LLM 用自
  己的话总结 / 翻译 / 回答问题
* 贴 ``xhslink.com/abc12`` 短链 → 自动 follow redirect 到完整 URL → 解析
* "这条小红书讲的什么" / "这篇笔记几张图" → 同上

### 反例（LLM 会拒绝）

用户："帮我搜小红书上 X 相关的笔记" 
→ LLM 回："Skyler 不主动爬小红书；你贴具体笔记链接给我就能解析"

用户："拉一下小红书首页推荐"
→ LLM 回："没这个能力。"

用户："我关注的人发了啥"
→ LLM 回："Skyler 不接小红书账号。如果你有具体链接想看可以贴给我。"

## 返回数据结构

```python
{
  "title": "笔记标题",
  "text": "正文（可能含 emoji / 话题标签 / 表情符）",
  "images": ["https://img1.jpg", "https://img2.jpg", ...],
  "author": "作者昵称",
  "tags": ["美食", "Vlog", ...],
  "url": "https://www.xiaohongshu.com/explore/abc123",  # follow 后的最终 URL
  "source": "initial_state" | "og_meta",  # 数据来源
}
```

或 error:

```python
{
  "error": "invalid_url" | "blocked_by_antibot" | "parse_failed" |
           "timeout" | "http_error" | "network_error" | "missing_url",
  "hint": "...",  # 部分 error 带友好提示
}
```

## 反爬限流

小红书 anti-bot 在以下情况会返 412/418：

* 短时间高频请求（10-20 req/min/IP 阈值）
* IP 是数据中心 / 云服务器（AWS / GCP / Azure / 阿里云）
* 缺少浏览器 fingerprint header

**Skyler 走个人家用 residential IP + 低频**，多数情况安全。但仍可能命
中限流，此时返 ``blocked_by_antibot``：

```
小红书暂时拒绝了请求（反爬限流）。可能原因：短时间内查询过多、
网络出口被识别为非常用 IP。等几分钟再试，或换网络环境。
```

LLM 会照实告诉用户，不假装结果。

## 排错

| 现象 | 可能原因 | 修法 |
|---|---|---|
| ``invalid_url`` | URL 不是 xiaohongshu.com / xhslink.com | 检查粘贴是否完整 |
| ``blocked_by_antibot`` | 反爬限流（412/418） | 等几分钟 / 换 WiFi / 重启路由器换 IP |
| ``parse_failed`` | 200 OK 但无可解析元数据 | 笔记可能是私人 / 已删 / xhs 改了模板（提 issue） |
| ``timeout`` | 网络慢 / 小红书慢 | 重试 |
| ``http_error`` | 5xx 服务器错 | 小红书侧问题，等会再试 |
| ``network_error`` | DNS / 网络断 | 检查能否打开 xiaohongshu.com |

## 数据源策略

```
HTTP 200 →
  ├─ 1. 优先解析 window.__INITIAL_STATE__（完整 title + desc + images + tags + author）
  │      undefined → null 修正 + 截到最后 } fallback
  ├─ 2. fallback og:title + og:description + og:image（缩略版）
  └─ 3. 都没 → parse_failed
```

实现细节见 ``backend/integrations/xiaohongshu.py``。

## 未来不会做（即使后续 prompt 要求）

工程契约层面坚决不实现：

* ❌ ``xhs.search_notes(keyword)``
* ❌ ``xhs.fetch_homepage()`` / ``xhs.fetch_feed()``
* ❌ ``xhs.get_user_posts(user_id)``
* ❌ ``xhs.like_post`` / ``xhs.collect`` / ``xhs.comment``
* ❌ session / login / token 管理
* ❌ 评论抓取

如果未来确实想接其中某项，应另起 chunk + 用户明确知情同意 + 走 MCP
server 隔离子进程（这样合规风险落在外部 server，Skyler 工程边界清晰）。

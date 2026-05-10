# B 站接入配置（v3.5 chunk 6a）

Skyler 集成 [Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api)
（社区活跃 fork）暴露 11 个 capability。两档使用模式：

| 模式 | 配置 | 可用 capability |
|---|---|---|
| **无登录**（默认） | 无需配置 | 6 个：search_video / get_video_info / search_user / get_user_videos / hot_videos / get_ranking |
| **登录后**（推荐） | `.env` 配 `BILIBILI_SESSDATA` | 全部 11 个（追加 5 个：get_subtitles ⭐ / get_my_history / get_my_followings / get_later_watch / get_favorites） |

⭐ **杀手 use case**：`get_subtitles` + LLM —— 用户粘 B 站视频链接说「帮我
总结一下」，Skyler 自动拿字幕用 Momo 的口气总结。**需要 cookie**（B 站
2024-2025 风控收紧字幕 API）。

## 配 SESSDATA（解锁 5 个 cookie capability）

1. Chrome / Edge 登录 [bilibili.com](https://www.bilibili.com)
2. 按 `F12` 打开 DevTools
3. 切到 **Application** tab → 左侧 **Cookies** → `https://www.bilibili.com`
4. 找到 **SESSDATA** 行 → 双击 Value 列 → Ctrl+A / Ctrl+C 复制
5. 编辑项目根 `.env`，找到（或新增）这一行：

   ```
   BILIBILI_SESSDATA=粘贴你的值
   ```

6. 重启 Skyler 后端（前端无需重启）

### 验证

启动后看 SettingsPanel → Capability Panel → 找 `bilibili.*` 行 → 健康徽
章应该是 🟢 `healthy`（``cookie_configured: true``）。若是 🟡 `warn` 说
明 cookie 没被读到——检查 `.env` 有没有空格 / 引号 / 路径错。

或者命令行快测：

```bash
.venv/bin/python -c "
import asyncio
from backend.integrations.bilibili import health_check
print(asyncio.run(health_check()))
"
```

## SESSDATA 安全提示

* SESSDATA **等同 B 站账号凭证**。别人拿到 = 可以以你的名义看私密视频、
  改个人资料、关注 / 取关任何人。
* **绝对不要**：commit 进 git / 贴 Discord 群 / 给客服看 / 上传 issue 截图
* Skyler 不在任何日志 / 错误信息 / 截屏里输出 SESSDATA 原值
* 你可以**随时撤销**：B 站设置 → 隐私设置 → 登出所有设备 → 重新登录 →
  再来一遍上面流程拿新 SESSDATA。这样老的立即失效
* 一般 1-3 个月失效一次（具体看你登录设备数 / 是否清浏览器 cookie），
  失效时 capability 会返 `cookie_required` 或 `bilibili_error`，重新走流程

## 完整 capability 列表

| Capability | Cookie | 用户触发语境 |
|---|---|---|
| `bilibili.search_video` | 否 | 「B 站搜 X」 |
| `bilibili.get_video_info` | 否 | 看到 B 站链接 / BV 号默认调 |
| `bilibili.search_user` | 否 | 「B 站搜 XX UP 主」 |
| `bilibili.get_user_videos` | 否 | 「XX 最近发了啥」（先 search_user 拿 mid） |
| `bilibili.hot_videos` | 否 | 「B 站现在有啥热门」 |
| `bilibili.get_ranking` | 否 | 「B 站排行榜」 |
| `bilibili.get_subtitles` ⭐ | **是** | 「这视频讲了啥 / 帮我总结 / 太长不看」 |
| `bilibili.get_my_history` | **是** | 「我最近在 B 站看了啥」 |
| `bilibili.get_my_followings` | **是** | 「我关注了哪些 UP 主」 |
| `bilibili.get_later_watch` | **是** | 「我的稍后再看」 |
| `bilibili.get_favorites` | **是** | 「我的 B 站收藏夹」 |

## 红线（不做的事）

Skyler **不实现**以下 B 站操作，工程主动拒绝（不在 capability registry）：

* ❌ 投币 / 一键三连 / 点赞 / 收藏（社区礼仪 + 风控敏感）
* ❌ 自动评论 / 弹幕发送
* ❌ 视频下载 / 录屏
* ❌ 私信 / 关注 / 取关（写操作一律不做）
* ❌ 直播弹幕监听 / 自动应援

> 如果未来想加这些，单独开 chunk 讨论 + 用户明确知情后启用。

## 排错

| 现象 | 可能原因 | 修法 |
|---|---|---|
| `health_check` 返 `library_missing` | 包没装 | `pip install bilibili-api-python>=17.4` |
| `health_check` 返 `connectivity: fail` | 网络 / B 站宕机 / 公司代理拦截 | 浏览器试试能否打开 bilibili.com |
| 调任何 capability 返 `cookie_required` | SESSDATA 没配 / 错 / 失效 | 重新走「配 SESSDATA」流程 |
| 调任何 capability 返 `risk_control` / `rate_limited` | 短时间内调太多次 | 等几分钟自然恢复 |
| 字幕 capability 返 `source: 'none'` | 该视频确实没有 AI 字幕和 UP 主字幕 | 不是 bug；让 Momo 如实告诉用户「这个视频没字幕」 |
| 字幕里有时间戳 / 重复 / 错别字 | B 站 AI 字幕本身质量 | LLM 总结时会处理；不要原样输出字幕给用户看 |

## 长字幕处理 backlog

第一版字幕全文返回不截断。**长视频（> 1 小时 / 字幕 > 30k 字符）**可能
吃 LLM context window 大量 token。当前能用是因为：
* qwen3.6-plus / claude / deepseek 都有 200k+ context
* B 站视频多为 5-30 分钟，字幕 1k-3k 字
* LLM 总结时本来就会压缩

如发现某些场景拖累，**ROADMAP Tech Debt** 已记「超长 B 站字幕分段总结
策略」backlog，后续可加：滑动窗口分段 → 各段单独总结 → 终极合并总结。

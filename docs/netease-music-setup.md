# 网易云音乐接入（v3-H chunk 1）

Skyler 内置网易云接入：通过网易云 web API 拿日推 / 歌单 / 搜索 + 唤起本机
**官方网易云 App** 播放。**不下载流、不绕版权、不需要任何第三方 SDK**。

## 一、装机要求

- macOS（其他平台只能拉数据，不能唤起 App）
- 已安装 **网易云音乐 macOS 客户端**（App Store / 官网下载）
- Skyler 后端依赖：``pycryptodome``（已写入 `requirements.txt`）

```bash
pip install -r requirements.txt
```

## 二、抓 MUSIC_U cookie

网易云 web API 鉴权靠 `MUSIC_U` cookie。Chrome 步骤：

1. 打开 <https://music.163.com> 用你的账号登录
2. **F12** → 顶栏切到 **Application**（中文版可能叫"应用"）
3. 左栏 → **Cookies** → 选 `https://music.163.com`
4. 在右侧表格里找 `MUSIC_U` 那一行
5. **双击 Value 单元格** → 复制全部（很长一串十六进制）

> Safari 用户：Develop → Show Web Inspector → Storage → Cookies。

## 三、写入 `.env`

在项目根目录的 `.env` 里：

```bash
NETEASE_MUSIC_U=粘贴你刚才复制的 MUSIC_U 值
```

⚠️ **MUSIC_U 等同账号凭证**：
- **不要 commit `.env`**（项目 `.gitignore` 已经排除）
- **不要分享给别人** —— 别人拿到后能完整登录你的账号
- **不要写到聊天 / 截图里**

## 四、验证

重启 Skyler backend：

```bash
uvicorn backend.main:app --reload
```

启动日志里应见 `netease.* registered`（7 个 capability）。打开前端 → 设置 → 能力面板 → "music" 类目应有 7 张卡片，所有卡片状态应是 **healthy** 绿点。如果是 **warn** 黄点，看错误信息：

| 错误信息 | 解释 + 修法 |
|---|---|
| 未配置 NETEASE_MUSIC_U cookie | `.env` 里 `NETEASE_MUSIC_U=` 是空的 → 按上面第二步抓 |
| cookie 失效或账号未登录 | MUSIC_U 过期了 → 浏览器登录一次重新抓（网易云 cookie 一般几个月才失效，但被风控 / 异地登录 / 手动改密码会立即失效）|
| 网络异常 | 国内能直连 music.163.com，挂代理时也基本不影响。如果代理 TUN 模式劫持 Python 流量可能出错 → 暂时关代理或换网络 |

## 五、聊天示例

跟 Momo 说，看后端日志的 `tool_calls`：

| 你说 | 期望工具序列 | 期望效果 |
|---|---|---|
| 放今天的日推 | `netease.daily_recommend` | 网易云 App 自动开播日推队列 |
| 随便放点 / 听点新的 | `netease.personal_fm` | App 进入私人 FM |
| 放一首夜空中最亮的星 | `netease.play_song` | App 直接放这首 |
| 放我那个跑步歌单 | `netease.play_playlist` → `netease.play_playlist_by_id` | LLM 模糊匹配出歌单 → App 开播 |
| 网易云有没有周杰伦的稻香 | `netease.search` | 返结果（不播放） |
| 好听！加红心 | `media.now_playing` → `netease.like_current` | 当前网易云歌曲被红心 |

## 六、能力清单（7 个）

| capability | 入参 | 行为 |
|---|---|---|
| `netease.daily_recommend` | 无 | 拉日推 → 唤起首歌 → App 接管队列 |
| `netease.personal_fm` | 无 | 唤起私人 FM (`orpheus://fm`) |
| `netease.play_song` | `keyword: str` | search → 第一个结果 → 唤起 |
| `netease.play_playlist` | 无 | **只列**用户所有歌单（让 LLM 自己挑）|
| `netease.play_playlist_by_id` | `playlist_id: int` | 唤起指定歌单 |
| `netease.like_current` | `title: str`, `artist?: str` | search → like |
| `netease.search` | `keyword`, `search_type` | 返结果，不播放 |

## 七、设计取舍

**为什么用 weapi 而不是 linuxapi / eapi？**
weapi 覆盖最完整，所有目标 capability 一条路径解决。代价：多一个 RSA 公钥模数 + AES 预设值，公开常量，与 jixunmoe / Binaryify 主流实现一致。

**为什么不直接调网易云后端流，而要唤起官方 App？**
绕版权 / 绕付费有法律和工程双重风险。把"决定播什么"交给 Skyler，把"放出来"交给官方 App，是边界最干净的方案。

**为什么 `play_playlist` 是两步而不是一步？**
歌单名常带 emoji / 别名 / 多语言（如 "🏃 跑步专用" / "🌃 night drive" / "学习 mix"），写代码做模糊匹配又脆又有偏见。让 LLM 看完整列表后用语义匹配是更好的分工。

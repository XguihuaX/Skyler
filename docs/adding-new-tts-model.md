# Adding a New TTS Model

INV-11 Stage 1.5 followup (2026-05-26) playbook · single source of truth for
扩 TTS provider × model 注册表。covers GSV (trained / zeroshot) + Fish。

---

## Where the registry lives

- `backend/config/tts_models.json` — 静态 provider × model 配置(label / mode /
  weights / server_url / inference_params / fish_latency / 等)
- `backend/tts/registry.py` — pydantic schema(`ModelSpec` / `ProviderSpec` /
  `TtsModelsConfig`)+ `_load_config()` + 公开 API(`list_providers` /
  `list_models` / `list_voices` / `get_provider_tree`)
- `backend/tts/gsv.py` / `backend/tts/__init__.py` (Fish 走 `tts/fish.py` 等)
  — runtime adapters · 直接读 `character.voice_model` JSON 的扁平字段(eg
  `gpt_weights` / `server_url`)· json 改 model entry 时这些字段透传到 DB

加 model 的流程都是 **改 json + 视情况 rsync 资源**。registry 加载时 pydantic
validate · 启动期 fail-fast(file 存在但 schema 损坏 → backend 拒绝启动 ·
带具体 pydantic 错误信息)。file 不存在 → hardcoded fallback(`registry.py::_hardcoded_fallback`)。

---

## Example 1 · 加一个 GSV trained model (e.g. `yae_v1`)

GSV trained = "训好的 GPT + SoVITS weights + 16 emotion ref · LLM emotion 输出
路由"。Mai_v4 是此范式 ship 的第一个。加 yae_v1:

### Step 1 · server 端准备 weights

把训好的 ckpt + pth 放进 GSV server (默认 `106.75.224.167:9880`):

```
/workspace/GPT-SoVITS/GPT_weights_v4/yae_v1-e15.ckpt
/workspace/GPT-SoVITS/SoVITS_weights_v4/yae_v1_e5_s1380_l32.pth
```

### Step 2 · server 端准备 emotion bank

16 emotion(默 set:`日常` / `开心` / `难过` / `生气` / ...· 见现 mai_v4
bank 同份)各一个 ref wav + 对应 lab 标注:

```
/workspace/GSVI/yae_emotion_bank/日常.wav
/workspace/GSVI/yae_emotion_bank/日常.lab
/workspace/GSVI/yae_emotion_bank/开心.wav
/workspace/GSVI/yae_emotion_bank/开心.lab
...
```

### Step 3 · 本地 rsync .lab 缓存

GSV TTS 启动时本地缓存 .lab(`GSVTTS._read_local_lab_files`)避免 16 次远端读。
SCP server 端 lab → 本地:

```bash
mkdir -p tts/gsv/yae_v1
scp -P 23 'root@106.75.224.167:/workspace/GSVI/yae_emotion_bank/*.lab' tts/gsv/yae_v1/
```

(wav 不需要本地 · 远端路径在 server 上 resolve)

### Step 4 · 编辑 `backend/config/tts_models.json`

在 `providers[].id="gsv"` 的 `models` 数组追加一个 entry:

```json
{
  "id": "yae_v1",
  "label": "Yae v1(八重神子 ja)",
  "mode": "trained",
  "tts_language": "ja",
  "gpt_weights": "GPT_weights_v4/yae_v1-e15.ckpt",
  "sovits_weights": "SoVITS_weights_v4/yae_v1_e5_s1380_l32.pth",
  "emotion_bank_dir": "tts/gsv/yae_v1",
  "remote_emotion_bank_dir": "/workspace/GSVI/yae_emotion_bank/",
  "default_emotion": "日常",
  "server_url": "http://106.75.224.167:9880",
  "inference_params": {
    "top_k": 15,
    "top_p": 1.0,
    "temperature": 1.0,
    "speed_factor": 1.0
  }
}
```

### Step 5 · backend restart

```bash
# pydantic validate + load 新 json · 失败会带具体错误信息
./scripts/restart-backend.sh   # 或 uvicorn reload · 视环境
```

### Step 6 · 前端 dropdown 自动显示

无需 frontend 改动 · `GET /api/tts/providers` 透传 json · VoicePicker 重新
fetch tree 就能选 `yae_v1`。

### Step 7 · 绑某个 character 到 yae_v1

UI 路径:角色管理 → 编辑 → TTS 声音 dropdown → provider=GSV → model=Yae v1
→ auto-save。或直接 PATCH:

```bash
curl -X PATCH http://127.0.0.1:8000/api/characters/2 \
  -H 'Content-Type: application/json' \
  -d '{"voice_model": "{\"provider\":\"gsv\",\"model\":\"yae_v1\",\"gpt_weights\":\"GPT_weights_v4/yae_v1-e15.ckpt\",\"sovits_weights\":\"SoVITS_weights_v4/yae_v1_e5_s1380_l32.pth\",\"tts_language\":\"ja\",\"emotion_bank_dir\":\"tts/gsv/yae_v1\",\"remote_emotion_bank_dir\":\"/workspace/GSVI/yae_emotion_bank/\",\"default_emotion\":\"日常\",\"server_url\":\"http://106.75.224.167:9880\",\"inference_params\":{\"top_k\":15,\"top_p\":1.0,\"temperature\":1.0,\"speed_factor\":1.0}}"}'
```

下一轮 chat · GSVTTS lazy-init `set_gpt_weights` / `set_sovits_weights` 自动切。

---

## Example 2 · 加一个 GSV zero-shot model (future · placeholder)

GSV zero-shot = "v4 pretrained base + 用户上传单个 ref audio + prompt text" ·
不需要 train · 不需要 emotion bank · 类似 Fish s2-pro reference upload 范式。

**当前 frontend UI 未实施** ref upload 流程(待第 1 个 zeroshot model 真用时
实施 · 复用 Fish reference upload component)。schema 已预留 · backend 字段
存在但 list_voices 返 placeholder。

### Step 1 · 编辑 `backend/config/tts_models.json`

在 `providers[].id="gsv"` 的 `models` 追加:

```json
{
  "id": "gsv-zeroshot-v4",
  "label": "GSV zero-shot v4(ref upload · 待实施)",
  "mode": "zeroshot",
  "tts_language": "ja",
  "server_url": "http://106.75.224.167:9880",
  "inference_params": {
    "top_k": 15,
    "top_p": 1.0,
    "temperature": 1.0,
    "speed_factor": 1.0
  }
}
```

(不写 `gpt_weights` / `sovits_weights` / `emotion_bank_dir` · zero-shot 用 v4
pretrained base · server 端默认 weights · 不切。)

### Step 2 · backend restart

注册 + tree 出现新 entry · 标记 `gsv_mode=zeroshot` · voice list 返
`requires_reference_upload=true` placeholder。

### Step 3 · frontend ref upload UI (待实施)

未来加第 1 个真用 zeroshot model 时:

1. VoicePicker 检测 `gsv_mode === "zeroshot"` → 显示 ref upload component
   (复用 Fish reference upload pattern)
2. 上传 wav + prompt text → POST `/api/tts/gsv/zeroshot/upload` (待实施)
3. backend 存 `reference_audio_path` + `reference_text` 进 character.voice_model
4. GSVTTS 检测 voice_model.mode=zeroshot → 走 zero-shot inference 路径
   (现 `GSVTTS.synth` 暂未实现该分支 · 加时一并补)

### Step 4 · server-side zero-shot inference

(待实施 · 当前 GSV server 已支持 zero-shot endpoint · 见
`/inference/zero_shot` · 路径 + payload 见 GPT-SoVITS upstream README)

---

## Example 3 · 加一个 Fish model (placeholder)

Fish provider 当前只有 `s2-pro` 一个 model。加新 (eg `agent-2`):

### Step 1 · 编辑 `backend/config/tts_models.json`

在 `providers[].id="fish"` 的 `models` 追加:

```json
{
  "id": "agent-2",
  "label": "Fish agent-2(cloud · 多语言)",
  "tts_language": "ja",
  "fish_latency": "fast"
}
```

(Fish reference 仍走 per-character upload · INV-12 Stage 2 已 ship backend
四 endpoint · 见 `backend/routes/tts_api.py`。new model 不需要 reference path
预设 · upload UI 触发存进 character.voice_model.reference_audio_path /
reference_text。)

### Step 2 · backend restart

dropdown 显示新 model · 用户在 VoicePicker 切到 fish · 选 model = agent-2 ·
点开 reference upload UI 上传 ref(同 INV-12 Stage 2 流程)。

---

## Schema reference (pydantic)

`ModelSpec` (`backend/tts/registry.py`):

| 字段                     | 类型     | required | 用途                                              |
|--------------------------|----------|----------|---------------------------------------------------|
| `id`                     | str      | ✓        | model id · 全局唯一 · 写进 voice_model.model      |
| `label`                  | str      | ✓        | 前端 dropdown 显示                                 |
| `tts_language`           | str      |          | "zh" / "ja" / "en" · 写进 voice_model.tts_language|
| `mode`                   | str      |          | GSV-only · "trained" (默认) / "zeroshot"          |
| `gpt_weights`            | str      |          | GSV trained · server 端路径                       |
| `sovits_weights`         | str      |          | GSV trained · server 端路径                       |
| `emotion_bank_dir`       | str      |          | GSV trained · 本地 .lab 缓存目录                  |
| `remote_emotion_bank_dir`| str      |          | GSV trained · server 端 wav 目录                  |
| `default_emotion`        | str      |          | GSV trained · fallback emotion · 默 "日常"         |
| `server_url`             | str      |          | GSV server URL                                    |
| `inference_params`       | dict     |          | GSV inference 参数 dict                           |
| `fish_latency`           | str      |          | Fish-only · "balanced" / "fast"                   |
| _extras_                 | -        |          | `extra="allow"` · 自定字段透传到 voice_model JSON |

provider-specific 字段不在 schema 里硬列也 OK(extras 允许)· 但建议加在
`ModelSpec` 显式字段(类型提示 + IDE 自动完成)。

---

## Troubleshooting

- **backend 启动报 `[tts-registry] ... schema 不匹配`** · 检查 json 字段拼写 /
  缺 required field · pydantic 错误信息给出具体 path
- **backend 启动报 `JSON 语法损坏`** · json 语法错(逗号 / 引号)· 用 `python -m
  json.tool backend/config/tts_models.json` validate
- **frontend dropdown 不显示新 model** · backend restart 没生效 · 或 frontend
  tree 缓存(VoicePicker mount 时 fetch · 切角色 / refresh tab 触发重 fetch)
- **GSV chat 报 weights 找不到** · `gpt_weights` / `sovits_weights` 路径与
  server 端实际不符 · SSH server `ls /workspace/GPT-SoVITS/GPT_weights_v4/`
  核对
- **应急回退 hardcoded fallback** · `mv backend/config/tts_models.json
  backend/config/tts_models.json.bak` · backend restart · log 会显示 "...
  不存在 · 使用 hardcoded fallback"。问题修好后 rename 回来

---

## Related lessons

- **Lesson INV-11 #13** · label 必须如实 reflect 行为(cosyvoice-v3.5-plus
  起初标 "复刻 voice 专用" 误导用户 · 真支持系统 + 复刻双轨)
- **Lesson INV-11 #14** · hardcoded vs json config 升级触发条件(model 数 ≥ 5
  + 加 model 不需 redeploy 时 · 升级 json 防 hardcoded 膨胀)
- **Lesson INV-11 #15** · GSV paradigm 2 mode(trained vs zeroshot)· schema
  设计前瞻 · mode 字段缺省视为 "trained" 向后兼容

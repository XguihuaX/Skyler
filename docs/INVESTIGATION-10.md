# Investigation 10 · v4.0 立绘馆 voice greeting feature

> 接 INV-9 Phase 2 整段 closed(2026-05-22)后第一刀。
> PM 决策启 voice greeting feature 作独立主线(Phase 3 streaming + Mai 真机最终验收延后到酒店再做,本 feature 不挡 Phase 3)。
> 设计:PM 提前上传音频文件,系统纯 storage + serve(不走 TTS 预渲染);立绘馆放大组件 onEnter 随机播放。

## reference list

- PM dispatch 2026-05-22 · v4.0 voice greeting + cid=101 Mai seed
- INV-9 §7 cost cap + cid=101 fish lock(`a6af74b`)— voice greeting 与 fish provider 解耦,纯 storage feature
- INV-8 §1.4.7 cid=101 三件事核实 — voice greeting 直接消费 cid=101 完整 Mai persona(per `1b25881` overlay)

## §1 backend ship(commit `2b597bc`, 2026-05-22)

### §1.1 改动清单

| 文件 | 改动 |
|---|---|
| `backend/database/migrations/v4_voice_greeting.py`(新) | CREATE TABLE `character_voice_lines`(id / character_id FK / audio_path / text_description / language / duration_ms / created_at)+ INDEX idx_voice_lines_character_id;幂等 |
| `backend/routes/voice_lines.py`(新 +250) | 4 endpoints · POST upload(multipart + 415/413 validate + UUID filename + duration extract + DB INSERT)/ GET list / GET random(404 if empty)/ DELETE(file + DB row)|
| `backend/main.py` | import migrate_v4_voice_greeting 注册 lifespan 1b34 / import voice_lines_router register /api prefix / **StaticFiles mount /static/voice_lines**(项目首次用 StaticFiles)|
| `tests/test_voice_lines.py`(新 +330 / 31 cases) | FastAPI TestClient · cid=4 凝光 dogfood + cleanup;404 unknown / 空 list / upload happy + duration + DB / list / random / DELETE + file unlink / 415 / 413 |
| `scripts/seed_mai_voice_lines.py`(新) | 6 Mai WAV from `scripts/fish_probe_outputs/` → backend/static/voice_lines/101/<uuid>.wav · INSERT 6 rows ja(canon range emotion markers 描述)|
| `requirements.txt` | + mutagen>=1.47.0(audio duration 提取) |
| `.gitignore` | + backend/static/voice_lines/(用户上传 audio 不进 git · 类 Live2D/splash-art IP 隔离) |

### §1.2 Lesson INV-10 #1 · Fish s2-pro WAV header `n_frames=INT_MAX` bug

mutagen 和 Python 标准 `wave` lib 对 Fish 生成 WAV 都报 `n_frames=2147483520`(INT_MAX)→ duration = 48695.77s(应 1-7s)。Fish 服务器 streaming 生成时 header 占位未回填真实样本数。

**Fix**:WAV 路径用 `file_size / bytes_per_sec` 推算(`sr × ch × sw` 从 header 读 OK,只 `n_frames` broken);mp3/ogg 仍走 mutagen `info.length`(bitrate-based 可信)。

```python
def _extract_duration_ms(file_path):
    if file_path.suffix == ".wav":
        with wave.open(str(file_path), "rb") as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        bytes_per_sec = sr * ch * sw
        audio_bytes = max(0, file_path.stat().st_size - 44)  # WAV header ~44B
        return int(round(audio_bytes / bytes_per_sec * 1000))
    # mp3/ogg via mutagen ...
```

**抽象**:第三方服务器生成的 audio header 字段不可全信(streaming 输出时常有占位/INT_MAX bug);body-size + format spec 推算是更 robust path。类比 INV-9 #6(SDK 字段表 ground truth)— INV-10 #1 是 audio container 层的同款"信任校准"。

### §1.3 Smoke · 31/31 cases / 6 seed verified

`tests/test_voice_lines.py` 31/31 PASS:
- 1.x: 404 unknown character(POST/GET list/GET random)
- 2.x: 空 list → 200 count=0;空 list random → 404
- 3.x: POST upload happy(multipart + duration + DB INSERT + file 落盘 + audio_url 形态)
- 4: GET list 含上传 row
- 5: GET random 非空 → 1 item
- 6.x: DELETE(file + DB row)+ unknown id 404
- 7.x: 415(非 audio MIME)+ 413(> 5MB)

Seed verify:cid=101 6 rows ids=[9-14]
- id=9 dur=6502ms 私、桜島麻衣...
- id=10 dur=1533ms [teasing] あら、来たのね
- id=11 dur=2415ms [composed]「君、今日は...」
- id=12 dur=1672ms [sarcastic]「あら、すごい...」
- id=13 dur=2043ms [teasing]「ほら、また当たった...」
- id=14 dur=1579ms [gentle]「あんまり無理しないで...」

## §2 frontend ship(commit 待 ship, 2026-05-22)

### §2.1 改动清单

| 文件 | 改动 |
|---|---|
| `frontend/src/lib/voice_lines.ts`(新) | API client · listVoiceLines / getRandomVoiceLine(404 空 list 返 null 静默)/ uploadVoiceLine(FormData)/ deleteVoiceLine / `playRandomVoiceGreeting` 主路径辅助 |
| `frontend/src/components/character/CharacterDetailModal.tsx` | + import playRandomVoiceGreeting + useEffect on mount → fetch random + play;unmount cleanup(pause)+ cancelled flag 防 race |
| `frontend/src/components/character/VoiceLinesSection.tsx`(新) | CharacterPanel "语音问候" section · 列表(text_description / duration / 语言 / ▶ preview / 🗑 delete)+ 上传 form(file + text_description + language select) |
| `frontend/src/components/CharacterPanel.tsx` | + import VoiceLinesSection · 在 form.mode === 'edit' + form.id !== null 时 render(类 PersonasSection 入口条件) |

### §2.2 立绘馆 onEnter 路径

```typescript
// CharacterDetailModal mount:
useEffect(() => {
  let cancelled = false;
  let audioEl: HTMLAudioElement | null = null;
  playRandomVoiceGreeting(character.id).then((a) => {
    if (cancelled) { if (a) a.pause(); }
    else { audioEl = a; }
  });
  return () => {
    cancelled = true;
    if (audioEl) try { audioEl.pause(); } catch {}
  };
}, [character.id]);
```

立绘馆 Gallery 浏览态 → 点中心卡 → handleSelect → `setDetailForId + setMode('detail')` → CharacterDetailModal mount → 上述 useEffect 触发 fetch + play。

### §2.3 Smoke · TypeScript clean

`yarn tsc --noEmit` clean(0 errors)。Frontend unit test 未写(per 项目 convention 多数 frontend 走真机测试);PM 真机:打开立绘馆点 Mai → 听 1 random voice greeting(seeded 6 条 Mai canon range markers ja audio)。

## §3 真机验收信号

PM 到酒店真机测试:
- Backend(已 ship)+ Frontend(本 commit)+ seed(已 ship)= 端到端
- 打开立绘馆(GalleryOpen)→ 点 Mai 卡(centerCharId=101)→ setMode('detail')→ CharacterDetailModal mount → fetch /api/character/101/voice_lines/random → 选 1 of 6 → new Audio + play
- 同时:CharacterPanel 编辑 cid=101 时看见 "🎙 语音问候" section,可看 6 seed rows + 试听 + 删除 + 上传新

预期听感:6 条 Mai 真合成 ja 1.5-6.5s 语音(per Mai canon range emotion markers · composed / teasing / sarcastic / gentle)。

## §4 后续

- Phase 3 流式管线 + H3 fix + Step 6 instrumentation(待 PM 真机最终验收 ↔ Mai chat hotfix 收敛)
- v4.1+ 多 provider 扩展刀(GPU 远程 + GSV)
- v4.1+ Mai emotion marker 实测精炼刀
- v4.1+ multi-user per-user cap 精确聚合
- v4.1+ voice_lines:Tier upgrade · 可加 emotion_tag / scene_tag 字段让 fetch 按情境过滤(per character mood / time-of-day / proactive_trigger);本轮 ship 是 minimum viable

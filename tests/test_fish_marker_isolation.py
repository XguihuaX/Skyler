"""INV-9 §5+§6 · per-provider [bracket] markers 双重隔离 unit test。

per PM Phase 2 第 3 commit Hard Req lock(2026-05-22):
  - 生成端(Layer A1 ja directive fish 子分支)教 LLM 在 <ja> 内嵌
    inline [bracket] markers
  - 接收端(_PreprocessingEngine per-provider 分流)决定是否 strip:
      provider == 'fish' → pass-through
      provider != 'fish' → strip(避免 cosyvoice/edge/sovits 念字面 marker)
  - 字幕层(strip_ja_en_tags_for_subtitle 链尾)跨 provider 一律剥

覆盖:
  1. strip_fish_emotion_markers 单元(正/负/边角 case)
  2. _PreprocessingEngine 分流(fish 不剥 / non-fish 剥)
  3. 集成:LLM raw → extract_tts_text → _PreprocessingEngine 端到端
  4. 字幕层:strip_ja_en_tags_for_subtitle 永远不含 [bracket]
  5. layer_a.j2 fish 子分支渲染(voice_provider='fish' 时含 marker 引导,
     voice_provider='cosyvoice' 时不含)
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (  # noqa: E402
    strip_fish_emotion_markers,
    strip_ja_en_tags_for_subtitle,
    extract_tts_text,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. strip_fish_emotion_markers 单元
# ---------------------------------------------------------------------------
def test_strip_single_marker():
    print("\n[1.1] 单 marker · [sarcastic] 剥除")
    out = strip_fish_emotion_markers("[sarcastic]ま、いいか。")
    check("剥 [sarcastic]", out == "ま、いいか。", detail=f"got {out!r}")


def test_strip_multi_markers():
    print("\n[1.2] 多 markers 跨句 · 全剥")
    text = "[soft chuckle]うん、まあね。[gentle]気にしないで。"
    out = strip_fish_emotion_markers(text)
    check("两 markers 全剥",
          out == "うん、まあね。気にしないで。",
          detail=f"got {out!r}")


def test_strip_mid_sentence():
    print("\n[1.3] mid-sentence · [whisper] 剥")
    text = "ね、ねえ[whisper]ちょっと聞いて。"
    out = strip_fish_emotion_markers(text)
    check("mid 剥", out == "ね、ねえちょっと聞いて。", detail=f"got {out!r}")


def test_strip_no_marker():
    print("\n[1.4] 无 marker · pass-through")
    text = "嗯,去吧。「うん、行きなさい。」"
    out = strip_fish_emotion_markers(text)
    check("原样不变", out == text, detail=f"got {out!r}")


def test_strip_empty_brackets_kept():
    print("\n[1.5] 空 [] / 空白 [   ] · 不剥(无 emotion 语义,保留)")
    out1 = strip_fish_emotion_markers("test[]end")
    out2 = strip_fish_emotion_markers("test[ ]end")
    check("[] 保留", out1 == "test[]end", detail=f"got {out1!r}")
    check("[ ] 剥(_FISH_RE 匹配 1+ 非括号字符,space 算非括号)",
          out2 == "testend", detail=f"got {out2!r}")


def test_strip_nested_brackets():
    print("\n[1.6] 嵌套 [outer[inner]] · regex 非贪婪 + 不允许嵌套")
    # _FISH_EMOTION_MARKER_RE = r"\[[^\[\]]+\]" — 不允许 inner [
    # 所以 [outer[inner]] 中第一个 [outer 不匹配(含 [),
    # [inner] 匹配 → out 'outer]'
    text = "[outer[inner]]余韵"
    out = strip_fish_emotion_markers(text)
    check("[inner] 剥 + [outer 残留 + ] 残留",
          out == "[outer]余韵", detail=f"got {out!r}")


def test_strip_chinese_brackets_not_affected():
    print("\n[1.7] 中文【】不剥(不是 [bracket])")
    text = "测试【中文括号】保留"
    out = strip_fish_emotion_markers(text)
    check("【】 保留", out == text)


def test_strip_edge_empty():
    print("\n[1.8] 空 / None")
    check("'' → ''", strip_fish_emotion_markers("") == "")
    check("None → None", strip_fish_emotion_markers(None) is None)


# ---------------------------------------------------------------------------
# 2. _PreprocessingEngine 分流(fish 不剥 / non-fish 剥)
# ---------------------------------------------------------------------------
class _CaptureTTS:
    """Mock TTSBase inner engine — 记录收到的 text 用于断言。"""
    def __init__(self) -> None:
        self.received: Optional[str] = None

    async def synthesize(self, text: str, emotion: str = "默认"):
        self.received = text
        return b"fake_audio"


def test_preprocessing_fish_passthrough():
    print("\n[2.1] _PreprocessingEngine provider='fish' · markers 透传")
    from backend.tts import _PreprocessingEngine

    inner = _CaptureTTS()
    engine = _PreprocessingEngine(inner, provider="fish")
    text = "[soft chuckle]「ま、いいか。」"
    asyncio.run(engine.synthesize(text))
    check("inner 收到含 [soft chuckle]",
          inner.received and "[soft chuckle]" in inner.received,
          detail=f"got {inner.received!r}")
    check("inner 收到含日语内容",
          inner.received and "「ま、いいか。」" in inner.received)


def test_preprocessing_cosyvoice_strips():
    print("\n[2.2] _PreprocessingEngine provider='cosyvoice' · markers 剥除")
    from backend.tts import _PreprocessingEngine

    inner = _CaptureTTS()
    engine = _PreprocessingEngine(inner, provider="cosyvoice")
    text = "[soft chuckle]「ま、いいか。」"
    asyncio.run(engine.synthesize(text))
    check("inner 收到不含 [soft chuckle]",
          inner.received and "[soft chuckle]" not in inner.received,
          detail=f"got {inner.received!r}")
    check("inner 收到含日语内容(emotion 剥后日语保留)",
          inner.received and "「ま、いいか。」" in inner.received)


def test_preprocessing_edge_strips():
    print("\n[2.3] _PreprocessingEngine provider='edge' · markers 剥(non-fish)")
    from backend.tts import _PreprocessingEngine

    inner = _CaptureTTS()
    engine = _PreprocessingEngine(inner, provider="edge")
    text = "[teasing]测试"
    asyncio.run(engine.synthesize(text))
    check("edge 路径剥 [teasing]",
          inner.received and "[teasing]" not in inner.received,
          detail=f"got {inner.received!r}")


def test_preprocessing_default_provider_strips():
    print("\n[2.4] _PreprocessingEngine 默认 provider='cosyvoice' · 剥 markers")
    from backend.tts import _PreprocessingEngine

    inner = _CaptureTTS()
    engine = _PreprocessingEngine(inner)  # 默 cosyvoice
    text = "[gentle]纯文本测试"
    asyncio.run(engine.synthesize(text))
    check("默认 provider 剥 markers",
          inner.received and "[gentle]" not in inner.received,
          detail=f"got {inner.received!r}")


def test_preprocessing_all_markers_empty_after_strip():
    print("\n[2.5] _PreprocessingEngine non-fish · 全 markers text → skip synth")
    from backend.tts import _PreprocessingEngine

    inner = _CaptureTTS()
    engine = _PreprocessingEngine(inner, provider="cosyvoice")
    # 全是 markers,strip 后空
    text = "[sarcastic][soft chuckle][gentle]"
    result = asyncio.run(engine.synthesize(text))
    check("全 markers strip 后空 → return None",
          result is None, detail=f"got {result!r}")
    check("inner.synthesize 未被调",
          inner.received is None)


# ---------------------------------------------------------------------------
# 3. 集成 · LLM raw → extract_tts_text → _PreprocessingEngine 端到端
# ---------------------------------------------------------------------------
def test_e2e_fish_path_preserves_markers():
    print("\n[3.1] e2e fish 路径 · LLM raw → 保留 markers")
    from backend.tts import _PreprocessingEngine

    # 模拟 LLM 输出:Mai 带 [soft chuckle] markers
    llm_raw = '"嗯,去吧。"<ja>[soft chuckle]「うん、行きなさい。」</ja>'
    # ws.py:959 路径:tts_text = extract_tts_text(sentence, 'ja')
    tts_text = extract_tts_text(llm_raw, "ja")
    check("extract_tts_text 保留 markers(ja 路径)",
          "[soft chuckle]" in tts_text and "「うん、行きなさい。」" in tts_text,
          detail=f"got {tts_text!r}")

    # 模拟 fish provider 走 _PreprocessingEngine
    inner = _CaptureTTS()
    engine = _PreprocessingEngine(inner, provider="fish")
    asyncio.run(engine.synthesize(tts_text))
    check("fish provider 透传 markers 给 SDK",
          inner.received and "[soft chuckle]" in inner.received,
          detail=f"got {inner.received!r}")


def test_e2e_cosyvoice_path_strips_markers():
    print("\n[3.2] e2e cosyvoice 路径 · LLM raw → 剥 markers")
    from backend.tts import _PreprocessingEngine

    # 假设 fallback 场景:LLM 学到 markers 但用户切到 cosyvoice voice
    # (历史 round-trip 锚点没 reset / 切换 in-flight),需 cosyvoice 路径剥除
    llm_raw = '"嗯,去吧。"<ja>[soft chuckle]「うん、行きなさい。」</ja>'
    tts_text = extract_tts_text(llm_raw, "ja")

    inner = _CaptureTTS()
    engine = _PreprocessingEngine(inner, provider="cosyvoice")
    asyncio.run(engine.synthesize(tts_text))
    check("cosyvoice provider 剥 [soft chuckle]",
          inner.received and "[soft chuckle]" not in inner.received,
          detail=f"got {inner.received!r}")
    check("日语内容保留",
          inner.received and "「うん、行きなさい。」" in inner.received)


# ---------------------------------------------------------------------------
# 4. 字幕层 · strip_ja_en_tags_for_subtitle 永远不含 [bracket]
# ---------------------------------------------------------------------------
def test_subtitle_strips_markers_in_zh():
    print("\n[4.1] subtitle 路径 · 中文 + <ja>[marker]日语</ja>")
    raw = '"嗯,去吧。"<ja>[soft chuckle]「うん、行きなさい。」</ja>'
    out = strip_ja_en_tags_for_subtitle(raw)
    check("subtitle 不含 [bracket]", "[" not in out and "]" not in out,
          detail=f"got {out!r}")
    check("subtitle 含中文",
          "嗯" in out and "去吧" in out)


def test_subtitle_strips_orphan_markers():
    print("\n[4.2] subtitle · 中文段误带 [bracket](LLM 错放)· 兜底剥")
    # LLM 错放 marker 到 display_zh 隐式段(<ja> 外)— 字幕层兜底剥
    raw = "[teasing]嗯,真好笑。<ja>「ま、いいか。」</ja>"
    out = strip_ja_en_tags_for_subtitle(raw)
    check("subtitle 不含 [teasing]", "[teasing]" not in out,
          detail=f"got {out!r}")
    check("subtitle 仍含中文", "嗯,真好笑。" in out)


def test_subtitle_no_marker_pass():
    print("\n[4.3] subtitle · 无 marker · pass-through")
    raw = '嗯,去吧。<ja>「うん、行きなさい。」</ja>'
    out = strip_ja_en_tags_for_subtitle(raw)
    check("subtitle 仅中文", out == "嗯,去吧。", detail=f"got {out!r}")


# ---------------------------------------------------------------------------
# 5. layer_a.j2 fish 子分支渲染(voice_provider 分流)
# ---------------------------------------------------------------------------
def test_layer_a_fish_branch_renders_marker_guide():
    print("\n[5.1] layer_a.j2 voice_provider='fish' · 渲染 markers 引导文")
    from backend.agents.prompt.renderer import _render_layer_a

    out = _render_layer_a(
        available_motions=[],
        tts_language="ja",
        voice_provider="fish",
    )
    check("含 [Fish s2-pro 句内情感 markers] 段头",
          "Fish s2-pro 句内情感 markers" in out)
    check("含 Mai 风格 marker 集示例",
          "[soft chuckle]" in out and "[teasing]" in out
          and "[composed]" in out)
    check("含明确禁用提示", "[excited]" in out and "[shouting]" in out
          and "禁用" in out)
    check("含 paren ≠ bracket 错误示范",
          "Fish 用 [bracket] 不是 (paren)" in out)


def test_layer_a_cosyvoice_no_marker_guide():
    print("\n[5.2] layer_a.j2 voice_provider='cosyvoice' · 不渲染 marker 引导")
    from backend.agents.prompt.renderer import _render_layer_a

    out = _render_layer_a(
        available_motions=[],
        tts_language="ja",
        voice_provider="cosyvoice",
    )
    check("不含 Fish markers 段",
          "Fish s2-pro 句内情感 markers" not in out)
    check("仍含 ja directive 主体",
          "日语 TTS 模式" in out and "中日交替" not in out  # 旧版没'中日交替'
          or "<ja>" in out)


def test_layer_a_zh_default_no_marker_guide():
    print("\n[5.3] layer_a.j2 tts_language='zh' · 任何 provider 都不渲染 ja markers")
    from backend.agents.prompt.renderer import _render_layer_a

    # zh + fish provider(理论可能未来出现)— ja directive 不进入,markers 也不教
    out = _render_layer_a(
        available_motions=[],
        tts_language="zh",
        voice_provider="fish",
    )
    check("zh 模式不进 ja directive",
          "日语 TTS 模式" not in out)
    check("zh 模式不教 Fish markers",
          "Fish s2-pro 句内情感 markers" not in out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    test_strip_single_marker()
    test_strip_multi_markers()
    test_strip_mid_sentence()
    test_strip_no_marker()
    test_strip_empty_brackets_kept()
    test_strip_nested_brackets()
    test_strip_chinese_brackets_not_affected()
    test_strip_edge_empty()
    test_preprocessing_fish_passthrough()
    test_preprocessing_cosyvoice_strips()
    test_preprocessing_edge_strips()
    test_preprocessing_default_provider_strips()
    test_preprocessing_all_markers_empty_after_strip()
    test_e2e_fish_path_preserves_markers()
    test_e2e_cosyvoice_path_strips_markers()
    test_subtitle_strips_markers_in_zh()
    test_subtitle_strips_orphan_markers()
    test_subtitle_no_marker_pass()
    test_layer_a_fish_branch_renders_marker_guide()
    test_layer_a_cosyvoice_no_marker_guide()
    test_layer_a_zh_default_no_marker_guide()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()

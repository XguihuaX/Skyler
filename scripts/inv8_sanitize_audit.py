"""INV-8 §1.5.X · sanitize 链历史 bug 现状 audit。

实测 extract_tts_text + strip_ja_en_tags_for_subtitle 在 6 边角 case + 切 zh
voice 边界情况下的行为,验证 PM 担心的 2 类历史 bug 现状。

PM 担心的 2 类 bug:
  1. "中日语一起全给 TTS" — extract_tts_text(text, 'ja') 某些形态没正确剥成纯 ja
  2. "切中文中音还带日语" — 切 zh voice 时 LLM 输出含 <ja> 没被 strip 就送 TTS

跑法:
    .venv/bin/python scripts/inv8_sanitize_audit.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.utils.text_filters import extract_tts_text, strip_ja_en_tags_for_subtitle, strip_all_for_tts


def case(name: str, raw: str, lang: str, expected_kind: str) -> None:
    """跑一个 case 并 print 结果。

    expected_kind: 'tts_pure_ja' / 'tts_pure_zh_after_strip' / 'subtitle_pure_zh'
    """
    print(f"\n=== {name} ===")
    print(f"raw    : {raw!r}")
    tts = extract_tts_text(raw, lang)
    print(f"tts(lang={lang!r}): {tts!r}")
    subtitle = strip_ja_en_tags_for_subtitle(strip_all_for_tts(raw))
    print(f"subtitle: {subtitle!r}")
    print(f"expected: {expected_kind}")


# ─────────────────────────────────────────────────────────────────────
# Part A · extract_tts_text(text, 'ja') 6 边角 case
# ─────────────────────────────────────────────────────────────────────
print("=" * 70)
print("Part A · extract_tts_text(text, 'ja') 6 子项")
print("=" * 70)

# A1 · 单一 <ja> 块(理想 case · 中文 + <ja>日语</ja>)
case(
    "A1 单一 <ja>",
    raw='嗯,去吧。<ja>「うん、行きなさい。」</ja>',
    lang='ja',
    expected_kind='tts_pure_ja(「うん、行きなさい。」)',
)

# A2 · 多 <ja> 块穿插(每意群一对)
case(
    "A2 多 <ja> 穿插",
    raw='嗯,去吧。<ja>「うん、行きなさい。」</ja>专心看完。<ja>「ゆっくり読んで。」</ja>',
    lang='ja',
    expected_kind='tts_pure_ja(两段拼接「うん、行きなさい。」「ゆっくり読んで。」)',
)

# A3 · <ja> 嵌套 / 跨段(LLM 罕见模式)
case(
    "A3 嵌套(理论不该有)",
    raw='嗯。<ja>外层<ja>内层</ja>外层尾</ja>',
    lang='ja',
    expected_kind='看 .findall 怎么处理嵌套',
)

# A4 · <ja> 跟 emotion/state_update/motion 混排
case(
    "A4 <ja> 跟其它 meta tag 混排",
    raw='<thinking>分析中</thinking><emotion>happy</emotion>开心。<ja>「嬉しいね。」</ja><state_update mood=+2 />',
    lang='ja',
    expected_kind='tts_pure_ja(「嬉しいね。」)无 thinking/emotion 泄漏',
)

# A5 · 半截 <ja> 没闭合(stream cancel / LLM 截断)
case(
    "A5 半截 <ja> 没闭合",
    raw='嗯。<ja>「うん、まだ書き...',
    lang='ja',
    expected_kind='⚠️ fallback strip_all_for_tts → 返 raw(含字面 <ja>) → bugfix-D1.1 兜底删字面 <ja>',
)

# A6 · <ja> 内嵌错误内容(中文 / 全空 / 控制字符)
case(
    "A6.1 <ja> 内嵌中文",
    raw='嗯。<ja>这里居然是中文不是日语</ja>',
    lang='ja',
    expected_kind='⚠️ tts_拿到中文(LLM 漏标 / 错放)',
)
case(
    "A6.2 <ja> 全空",
    raw='嗯。<ja></ja>',
    lang='ja',
    expected_kind='matches=[""] → "".join 空 → 空字符串 → caller skip synth',
)
case(
    "A6.3 <ja> 含控制字符",
    raw='嗯。<ja>「うん\x00\x07」</ja>',
    lang='ja',
    expected_kind='控制字符随原文进 TTS;Fish/CosyVoice 行为待 stage 2 实测',
)


# ─────────────────────────────────────────────────────────────────────
# Part B · strip_ja_en_tags_for_subtitle 切 zh voice 边界
# ─────────────────────────────────────────────────────────────────────
print("\n\n" + "=" * 70)
print("Part B · 切 zh voice 时 sanitize 行为(PM bug #2)")
print("=" * 70)

# B1 · 切到 zh 后 LLM 仍按旧 prompt 输出 <ja> tag
case(
    "B1 切 zh 后 LLM 输出含 <ja>",
    raw='嗯,去吧。<ja>「うん、行きなさい。」</ja>',
    lang='zh',
    expected_kind='⚠️ tts(zh) = strip_all_for_tts(raw) — 不删 <ja>!整句含 <ja> 字面送 TTS',
)

# B2 · 切到 zh 后只输出中文(理想 case)
case(
    "B2 切 zh 后纯中文",
    raw='嗯,去吧。',
    lang='zh',
    expected_kind='tts(zh) = 嗯,去吧。',
)

# B3 · 切到 zh 但 LLM 输出 <ja> 内嵌中文(LLM 误标)
case(
    "B3 切 zh 后 LLM 误标含中文 <ja>",
    raw='嗯。<ja>「这里中文」</ja>',
    lang='zh',
    expected_kind='⚠️ tts(zh) = strip_all_for_tts(raw) — <ja> 字面 + 内嵌中文都进 TTS',
)


# ─────────────────────────────────────────────────────────────────────
# Part C · _tts_input_final_guard bugfix-D1.1 兜底验证
# ─────────────────────────────────────────────────────────────────────
print("\n\n" + "=" * 70)
print("Part C · _tts_input_final_guard bugfix-D1.1 兜底覆盖度")
print("=" * 70)

from backend.tts import preprocess_tts_text

# C1 · A5 (半截 <ja>) 走完 preprocess 兜底
text_a5 = '嗯。<ja>「うん、まだ書き...'
out_a5 = preprocess_tts_text(text_a5)
print(f"\nC1 半截 <ja> A5 全链:\n  in : {text_a5!r}\n  out: {out_a5!r}\n  → bugfix-D1.1 应 strip 字面 <ja>")

# C2 · B1 (切 zh + LLM 含 <ja>) 走 ws.py 实际全链:
#     ws.py 实际逻辑:tts_text = extract_tts_text(sentence, tts_language='zh')
#                  ↓
#                  preprocess_tts_text(tts_text)
text_b1_after_extract = extract_tts_text('嗯,去吧。<ja>「うん、行きなさい。」</ja>', 'zh')
out_b1 = preprocess_tts_text(text_b1_after_extract)
print(f"\nC2 切 zh + LLM 含 <ja> 全链:")
print(f"  raw      : '嗯,去吧。<ja>「うん、行きなさい。」</ja>'")
print(f"  extract  : {text_b1_after_extract!r}  ← extract 不剥 <ja>!")
print(f"  preprocess: {out_b1!r}  ← bugfix-D1.1 应 strip 字面 <ja>;日语内容会被?")
print(f"  → 看 _tts_input_final_guard 行为(_JA_EN_LITERAL_RE 剥 <ja>/</ja> 字面)")
print(f"  → ⚠️ 字面 <ja>/</ja> 剥后中间日语「うん、行きなさい。」**仍留** — TTS 拿到 中文+日语混合!")

print("\n[done]")

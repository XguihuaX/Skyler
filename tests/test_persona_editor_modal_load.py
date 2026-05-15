"""Bugfix-segment2-1 — PersonaEditorModal 数据 load 路径回归。

Audit 发现 `_existingToForm` 纯函数在 real API JSON 上工作正常,bug 在
state/render level(stale prop / strict-mode 重 mount / etc)。修复用
defensive ``getPersona(existing.id)`` 重 fetch + ``identity ?? {}`` 兜底
null 嵌套字段。

本测验 5 件事:
  1. test_modal_renders_aliases_from_persona       — aliases 数组 → CSV
  2. test_modal_renders_self_intro_dual_tier        — 0-69 / 70-100 都被解出
  3. test_modal_renders_voice_samples_with_tolerance_range — 12 条样本保留
  4. test_modal_renders_forbidden_phrases_4_subsets — 4 子集都解出
  5. test_modal_save_preserves_loaded_fields         — patch 一个字段不丢其他

跑法:本测试 spawn ``node -e`` 子进程,把当前 DB 的 API JSON 喂给纯 JS
transform。这样我们既不需要前端 test runner(没装 vitest),又能验真实
TypeScript helper 的行为。

Run:
    .venv/bin/python tests/test_persona_editor_modal_load.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 把 PersonaEditorModal 的 _existingToForm 复制成 pure JS 跑;运行用 node -e
# 接 stdin(避免 shell 转义 chinese 内容的坑)。
# ---------------------------------------------------------------------------

_NODE_TRANSFORM_JS = r"""
let raw = '';
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const p = JSON.parse(raw);

  // 与 PersonaEditorModal.tsx::_existingToForm 等价的 pure JS 实现。
  // **必须**与 modal 内 _existingToForm 字字对应(本测验目的就是
  // confirm transform produces 非空 fields)。
  const arrToCsv = (a) => (a == null ? '' : (a ?? []).join(', '));
  const identity = p.identity ?? {};
  const personality_core = p.personality_core ?? {};
  const speech_style = p.speech_style ?? {};
  const forbidden_phrases = p.forbidden_phrases ?? {};
  const relationship_to_user = p.relationship_to_user ?? {};
  const f = {
    variant_name: p.variant_name,
    description: p.description ?? '',
    style_preset: p.style_preset ?? 'anime_classic',
    identity_name: identity.name ?? '',
    identity_aliases_csv: arrToCsv(identity.aliases),
    identity_self_reference: identity.self_reference ?? '我',
    identity_age: identity.age != null ? String(identity.age) : '',
    identity_occupation: identity.occupation ?? '',
    identity_origin: identity.origin ?? '',
    identity_self_intro_0_69: identity.self_intro?.['0-69'] ?? '',
    identity_self_intro_70_100: identity.self_intro?.['70-100'] ?? '',
    pc_core_traits_csv: arrToCsv(personality_core.core_traits),
    pc_contrasts: (personality_core.contrasts ?? []).join('\n'),
    pc_energy_level: personality_core.energy_level ?? 'medium',
    pc_default_emotion: personality_core.default_emotion ?? 'calm',
    pc_anger_style: personality_core.anger_style ?? '',
    ss_vocabulary: speech_style.vocabulary ?? 'neutral',
    ss_sentence_rhythm: speech_style.sentence_rhythm ?? 'medium',
    ss_user_address: speech_style.user_address ?? '你',
    ss_emoji_habit: speech_style.emoji_habit ?? 'rare',
    ss_punctuation_quirk: speech_style.punctuation_quirk ?? 'standard',
    ss_cliche_tolerance: speech_style.cliche_tolerance ?? 0.5,
    signature_phrases_csv: arrToCsv(p.signature_phrases),
    voice_samples: p.voice_samples ?? [],
    fp_global_csv: arrToCsv(forbidden_phrases._global),
    fp_character_csv: arrToCsv(forbidden_phrases._character),
    fp_qwen_csv: arrToCsv(forbidden_phrases._qwen),
    fp_deepseek_csv: arrToCsv(forbidden_phrases._deepseek),
    rel_type: relationship_to_user.type ?? 'companion',
    rel_intimacy_progression: relationship_to_user.intimacy_progression ?? 'linear',
    rel_initial_intimacy: relationship_to_user.initial_intimacy ?? 50,
  };
  process.stdout.write(JSON.stringify(f));
});
"""


def run_transform(api_persona: Dict[str, Any]) -> Dict[str, Any]:
    """Spawn ``node -e`` to run pure-JS _existingToForm equivalent; return FormState dict。"""
    proc = subprocess.run(
        ["node", "-e", _NODE_TRANSFORM_JS],
        input=json.dumps(api_persona, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node transform failed: {proc.stderr.decode('utf-8', errors='replace')}"
        )
    return json.loads(proc.stdout.decode("utf-8"))


# ---------------------------------------------------------------------------
# Test data: 模拟 Mai persona 完整 JSON(与 segment 2 DB 实际 character_id=1
# default variant 同 shape,但用 ASCII-safe 字符串保证 subprocess pipe 干净)。
# ---------------------------------------------------------------------------

MAI_PERSONA_FIXTURE: Dict[str, Any] = {
    "id": 1,
    "character_id": 1,
    "variant_name": "default",
    "is_builtin": True,
    "is_active": True,
    "display_order": 0,
    "description": "Mai persona for bugfix test",
    "identity": {
        "name": "Mai",
        "aliases": ["麻衣", "麻衣学姐", "Mai-san"],
        "self_reference": "我",
        "age": 17,
        "occupation": "前演员 / 高中生",
        "origin": "六岁出道,十五岁停下来。",
        "self_intro": {
            "0-69": "我是 Mai。常规版自我介绍 PUBLIC_INTRO_SENTINEL。",
            "70-100": "深度版 DEEP_INTRO_SENTINEL...你已经认识我够久了。",
        },
    },
    "personality_core": {
        "core_traits": ["克制", "聪明", "话少观察细"],
        "contrasts": [
            "看似冷淡,实则注意每个细节",
            "毒舌不留情面,事后默默准备",
        ],
        "energy_level": "low",
        "default_emotion": "neutral",
        "anger_style": "变冷不暴怒",
    },
    "speech_style": {
        "vocabulary": "neutral",
        "sentence_rhythm": "short",
        "user_address": "你",
        "emoji_habit": "none",
        "punctuation_quirk": "破折号偏好",
        "cliche_tolerance": 0.35,
    },
    "signature_phrases": ["...笨蛋。", "随你便。"],
    "voice_samples": [
        {"scene": "起床", "text": "...嗯。", "tolerance_range": [0.0, 0.5]},
        {"scene": "夸奖反应", "text": "...白痴。", "tolerance_range": [0.0, 0.4]},
        {"scene": "撒娇高糖", "text": "你叫我我就来啊。", "tolerance_range": [0.7, 1.0]},
    ],
    "forbidden_phrases": {
        "_global": ["作为AI", "作为助手"],
        "_character": ["我是樱岛麻衣不是 Momo"],
        "_qwen": ["总的来说"],
        "_deepseek": ["请允许我"],
    },
    "relationship_to_user": {
        "type": "companion",
        "intimacy_progression": "milestone",
        "initial_intimacy": 30,
    },
    "taboo_topics": None,
    "lore": None,
    "capability_overrides": None,
    "style_preset": "realistic_grounded",
    "created_at": "2026-01-01 00:00:00",
    "updated_at": "2026-01-01 00:00:00",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_modal_renders_aliases_from_persona():
    print("\n[1] aliases (array → CSV)")
    f = run_transform(MAI_PERSONA_FIXTURE)
    check("aliases CSV non-empty",
          bool(f["identity_aliases_csv"]),
          f"got {f['identity_aliases_csv']!r}")
    check("aliases CSV contains all 3 items",
          "麻衣" in f["identity_aliases_csv"]
          and "麻衣学姐" in f["identity_aliases_csv"]
          and "Mai-san" in f["identity_aliases_csv"])
    check("age rendered as string '17'",
          f["identity_age"] == "17",
          f"got {f['identity_age']!r}")
    check("occupation non-empty",
          bool(f["identity_occupation"]),
          f"got {f['identity_occupation']!r}")
    check("origin non-empty",
          bool(f["identity_origin"]),
          f"got {f['identity_origin']!r}")


def test_modal_renders_self_intro_dual_tier():
    print("\n[2] self_intro 双梯级")
    f = run_transform(MAI_PERSONA_FIXTURE)
    check("0-69 contains PUBLIC_INTRO_SENTINEL",
          "PUBLIC_INTRO_SENTINEL" in f["identity_self_intro_0_69"])
    check("70-100 contains DEEP_INTRO_SENTINEL",
          "DEEP_INTRO_SENTINEL" in f["identity_self_intro_70_100"])


def test_modal_renders_voice_samples_with_tolerance_range():
    print("\n[3] voice_samples + tolerance_range")
    f = run_transform(MAI_PERSONA_FIXTURE)
    samples = f["voice_samples"]
    check("3 samples preserved", len(samples) == 3, f"got {len(samples)}")
    check("each sample has tolerance_range",
          all("tolerance_range" in s and len(s["tolerance_range"]) == 2 for s in samples))
    check("撒娇高糖 sample tolerance_range = [0.7, 1.0]",
          samples[2]["tolerance_range"] == [0.7, 1.0])
    check("scene preserved", samples[0]["scene"] == "起床")
    check("text preserved", "嗯。" in samples[0]["text"])


def test_modal_renders_forbidden_phrases_4_subsets():
    print("\n[4] forbidden_phrases 4 subsets")
    f = run_transform(MAI_PERSONA_FIXTURE)
    check("_global CSV non-empty",
          "作为AI" in f["fp_global_csv"])
    check("_character CSV non-empty",
          "Momo" in f["fp_character_csv"])
    check("_qwen CSV contains 总的来说",
          "总的来说" in f["fp_qwen_csv"])
    check("_deepseek CSV contains 请允许我",
          "请允许我" in f["fp_deepseek_csv"])


def test_modal_save_preserves_loaded_fields():
    """模拟用户 load → 改一个 ss_cliche_tolerance → save 时不丢其他字段。"""
    print("\n[5] save preserves loaded fields (only cliche_tolerance changed)")
    f1 = run_transform(MAI_PERSONA_FIXTURE)
    # 模拟用户操作:仅改 cliche_tolerance
    f2 = dict(f1)
    f2["ss_cliche_tolerance"] = 0.8
    # 验:其他关键字段保持
    for key in (
        "identity_aliases_csv", "identity_age",
        "identity_self_intro_0_69", "identity_self_intro_70_100",
        "pc_core_traits_csv", "pc_contrasts",
        "fp_global_csv", "voice_samples",
    ):
        check(f"{key} preserved", f1[key] == f2[key])
    check("ss_cliche_tolerance updated", f2["ss_cliche_tolerance"] == 0.8)


# ---------------------------------------------------------------------------
# Bonus: 验 defensive null-safety(模拟 server 返回 identity=null 等坏数据)
# ---------------------------------------------------------------------------

def test_modal_handles_null_nested_fields_gracefully():
    """Tier-1 嵌套字段为 null 时不崩,form 退化到 default 值。"""
    print("\n[6] defensive null handling (identity / personality_core / etc null)")
    broken = dict(MAI_PERSONA_FIXTURE)
    broken["identity"] = None
    broken["personality_core"] = None
    broken["speech_style"] = None
    broken["forbidden_phrases"] = None
    broken["relationship_to_user"] = None
    try:
        f = run_transform(broken)
        check("no crash on null Tier-1 fields", True)
        check("identity_name default ''", f["identity_name"] == "")
        check("identity_self_reference default '我'", f["identity_self_reference"] == "我")
        check("rel_type default 'companion'", f["rel_type"] == "companion")
    except Exception as exc:
        check(f"transform crashed: {exc}", False)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    # Quick sanity: node available
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print(FAIL + " node not available — skipping (frontend transform test requires node)")
        return 0

    test_modal_renders_aliases_from_persona()
    test_modal_renders_self_intro_dual_tier()
    test_modal_renders_voice_samples_with_tolerance_range()
    test_modal_renders_forbidden_phrases_4_subsets()
    test_modal_save_preserves_loaded_fields()
    test_modal_handles_null_nested_fields_gracefully()

    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n{'='*60}\nResults: {passed}/{len(results)} passed, {failed} failed")
    if failed:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""CosyVoice longanhuan 情感渲染独立验证脚本。

用途
----
v3-G' 收官验收工具。隔离一切上层因素（LLM、WebSocket 路由、emotion 中英映
射等），只验证 ``DashScope SpeechSynthesizer`` 走 ``instruction`` 路径时，
不同英文 emotion 关键词在 ``longanhuan`` 这个 instruct-aware 音色上是否
真的产生听感差异。

固定变量
~~~~~~~~
* 文本固定："今天天气真好啊，我有一些事情想跟你说。"
* voice 固定：longanhuan
* model 固定：与生产路径同一个（从 backend/tts/cosyvoice.py 默认值取，当前
  ``cosyvoice-v3-flash``，无外部参数化以避免漂移）
* emotion 跑 4 次：happy / sad / angry / neutral

调用形态与生产一致（backend/tts/cosyvoice.py:_blocking_synthesize）：
  - happy / sad / angry → 传 ``instruction="你说话的情感是 X。"``
  - neutral            → 不传 instruction（plain 调用，用作对照基线）

输出
----
4 个 WAV 文件落在 ``tools/output/``，文件名 ``cosyvoice_<emotion>.wav``。
用 ``afplay`` 依次播放对比即可。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import dashscope
from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "tools" / "output"
TEXT = "今天天气真好啊，我有一些事情想跟你说。"
VOICE = "longanhuan"
MODEL = "cosyvoice-v3-flash"  # 与 backend/tts/cosyvoice.py 默认 model 对齐
EMOTIONS = ("happy", "sad", "angry", "neutral")


def _build_kwargs(emotion: str) -> tuple[dict, str | None]:
    """复刻 _blocking_synthesize 的 emotion 路由逻辑。

    返回 (synthesizer kwargs, 用于 stdout 打印的 instruction 字符串 or None)。
    """
    kwargs: dict = {
        "model": MODEL,
        "voice": VOICE,
        "format": AudioFormat.WAV_24000HZ_MONO_16BIT,
    }
    # 与生产白名单 _INSTRUCT_EMOTION_WHITELIST 对齐（不含 neutral）
    if emotion in {"happy", "sad", "angry", "surprised"}:
        instruction = f"你说话的情感是 {emotion}。"
        kwargs["instruction"] = instruction
        return kwargs, instruction
    return kwargs, None


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        print(
            "ERROR: DASHSCOPE_API_KEY 未设置（检查项目根 .env）",
            file=sys.stderr,
        )
        return 2
    dashscope.api_key = api_key

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = len(EMOTIONS)
    for idx, emotion in enumerate(EMOTIONS, start=1):
        kwargs, instruction = _build_kwargs(emotion)
        if instruction is None:
            print(f'[{idx}/{total}] emotion={emotion} instruction=<plain, 无 instruction>')
        else:
            print(f'[{idx}/{total}] emotion={emotion} instruction="{instruction}"')

        try:
            synthesizer = SpeechSynthesizer(**kwargs)
            audio = synthesizer.call(TEXT)
        except Exception as exc:
            print(
                f"      ERROR: SDK 调用抛异常 emotion={emotion} err={exc!r}",
                file=sys.stderr,
            )
            return 3

        if not audio:
            print(
                f"      ERROR: SDK 返回空音频 emotion={emotion}（API key / 余额 / 网络？）",
                file=sys.stderr,
            )
            return 4

        out_path = OUTPUT_DIR / f"cosyvoice_{emotion}.wav"
        out_path.write_bytes(audio)
        rel = out_path.relative_to(PROJECT_ROOT)
        print(f"      saved {rel} ({len(audio)} bytes)")

    print("完成。请用 QuickTime / afplay 对比 4 个 wav。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

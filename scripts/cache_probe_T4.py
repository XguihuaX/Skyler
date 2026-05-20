"""T4 · tools= 列表 cache_control pass-through 实测.

测点: dashscope/qwen3.6-max-preview + tools[最后一个].cache_control:{ephemeral}
target: 验证 LiteLLM dashscope/ 路径是否 pass-through tools 列表内的 cache_control
        给 DashScope 端点,并产生覆盖 tools schema 那部分的 cached_tokens。

baseline 排除:
  - system 是短稳定 string(~200-300 token),**无 cache_control marker**
  - 若 cached_tokens >> 200-300 → 命中包含了 tools schema 段
  - 若 cached_tokens ≤ 300 → 仅 system 被自动 cache(或者根本没命中)

payload:
  - system: 短 instruction (固定字面)
  - tools: 15 个合成 dummy function-call schema,字面稳定,总 >= 1024 token
           最后一个 tool dict 顶层加 ``cache_control: {"type":"ephemeral"}``
           (Anthropic SDK 官方语义位置)
  - user: 短问句

跑 2 次(不同 user 短句,相同 system+tools),1.5s 间隔,
抓 response.usage 完整字段。
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cache_probe_payload import dump_result, pretty


MODEL = "dashscope/qwen3.6-max-preview"

# baseline system: 短稳定字面,约 200-300 token,无 cache_control
SHORT_SYSTEM = """你是一个用于 prompt caching tools= 列表 cache_control 实测的稳定角色。
对所有 user 输入,严格回答"测试已收到。"这 6 个字符(含末尾句号),不解释、不调用任何 tool、不返回 JSON。
你不需要友善、不需要陪伴。该规则优先级最高,无任何例外。"""


def _build_synthetic_tools() -> list:
    """构造 15 个合成 dummy tool schema,字面稳定,总 token 估 >= 1500。

    每个 tool 含:
      - 较长 description(约 60-100 中文字 ≈ 60-100 token)
      - parameters_schema 含 3-5 个 properties,每个 property 含较长 description

    最后一个 tool dict 顶层标 cache_control: {"type":"ephemeral"}
    """
    tool_specs = [
        ("search_documents", "在用户的本地文档库中按关键词搜索匹配文件,返回最多 N 条结果。"
            "支持模糊匹配、文件名匹配、内容片段匹配三种模式。当用户问'我那个 X 文档放哪了'时调用。"),
        ("create_calendar_event", "在用户的日历(Apple Calendar / Google Calendar)上创建一个事件。"
            "需要标题、起始时间(ISO 8601)、持续时长(分钟,默认 30)、可选描述。"),
        ("list_recent_emails", "拉取用户最近 N 封未读邮件的标题与发件人摘要,不读正文。"
            "支持按发件人过滤、按主题关键词过滤、按时间窗口过滤。"),
        ("translate_text", "把任意源语言文本翻译到目标语言。支持中英日韩法德西俄等十种语言。"
            "保留原文格式标记(markdown / HTML)。当用户说'帮我翻译这段'时调用。"),
        ("summarize_long_text", "对长文档做摘要压缩,保留核心论点。"
            "支持指定摘要长度(短/中/长)、风格(中性/学术/通俗)、是否保留引用。"),
        ("generate_image", "根据自然语言 prompt 生成一张图像。支持指定尺寸、风格、负面 prompt。"
            "当用户说'画一张 X'或'生成 X 的图'时调用。"),
        ("query_weather", "查询指定城市或经纬度的当前天气与未来 N 天预报。"
            "返回温度、降水、风力、湿度、空气质量、紫外线指数。"),
        ("search_web", "用搜索引擎查询关键词,返回 top N 网页摘要 + URL。"
            "当用户问需要联网才能回答的事实性问题时调用,如'最新的 X 是什么'。"),
        ("read_pdf", "读取沙箱中的 PDF 文档内容并提取纯文本。"
            "支持指定页码范围、是否保留表格结构、是否提取图像 OCR 文字。"),
        ("write_markdown", "在沙箱目录创建一个 markdown 文档。"
            "需要文件名、内容主体、可选 front matter(yaml)、可选目录归属。"),
        ("query_database", "在用户授权的数据库中执行一条只读 SQL 查询。"
            "限制 SELECT only,不允许 INSERT/UPDATE/DELETE/DROP。"),
        ("set_reminder", "设置一个本地提醒,在指定时间触发系统通知。"
            "需要标题、触发时间(ISO 8601)、可选重复规则(daily/weekly/monthly)。"),
        ("get_stock_price", "查询指定股票代码的当前价格、涨跌幅、成交量。"
            "支持 A 股、港股、美股市场。当用户问'X 股票现在多少'时调用。"),
        ("convert_currency", "外汇换算。需要源币种、目标币种、金额。"
            "返回当前汇率与换算后的目标币种金额。"),
        ("get_movie_info", "查询电影元数据,含上映年份、导演、主演、剧情简介、评分。"
            "支持按电影名、按导演、按演员三种检索方式。"),
    ]

    tools: list = []
    for i, (name, desc) in enumerate(tool_specs):
        tool: dict = {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "主参数,该 tool 的核心输入字符串,语义按 tool 定义。",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回条目数量上限,默认 10,范围 1-100。",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "options": {
                            "type": "object",
                            "description": "可选高级参数对象,内含 tool-specific 子字段。",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["query"],
                },
            },
        }
        # 在最后一个 tool 顶层标 cache_control(Anthropic SDK 官方语义)
        if i == len(tool_specs) - 1:
            tool["cache_control"] = {"type": "ephemeral"}
        tools.append(tool)
    return tools


def build_messages(user_text: str) -> list:
    return [
        {"role": "system", "content": SHORT_SYSTEM},
        {"role": "user", "content": user_text},
    ]


async def run_once(label: str, user_text: str, tools: list) -> dict:
    from backend.llm.client import call_llm

    t0 = time.perf_counter()
    try:
        resp = await call_llm(
            messages=build_messages(user_text),
            model=MODEL,
            stream=False,
            tools=tools,
        )
    except Exception as exc:
        return {
            "label": label,
            "error": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc()[:2000],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    return dump_result(label, resp, (time.perf_counter() - t0) * 1000)


async def main() -> None:
    tools = _build_synthetic_tools()

    # 粗算 tools schema 字符 (字符 ≈ 0.7-1.0 token for ascii-heavy json + 中文 description)
    import json as _json
    tools_json_chars = len(_json.dumps(tools, ensure_ascii=False))

    print(f"[T4] model = {MODEL}")
    print(f"[T4] system_text chars = {len(SHORT_SYSTEM)} (baseline, no cache_control)")
    print(f"[T4] tools count = {len(tools)}")
    print(f"[T4] tools json chars = {tools_json_chars}")
    print(f"[T4] cache_control marker = on tools[-1] (Anthropic 顶层语义)")
    print("=" * 70)

    r1 = await run_once("T4.call_1_cold", "你好", tools)
    print(pretty(r1))
    print("-" * 70)

    await asyncio.sleep(1.5)

    r2 = await run_once("T4.call_2_warm", "再来一次", tools)
    print(pretty(r2))
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

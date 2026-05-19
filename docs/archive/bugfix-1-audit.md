# Bugfix-1 Audit — LLM hallucinated tag 泄露

## 1. Tool-call 机制（搞清楚我们要保留什么）

MomoOS 同时使用**两条** tool-call 通道，必须分清楚：

**A. 真 tool calling（OpenAI function-calling protocol）**
- 走 `delta.tool_calls`，**不进** `delta.content`
- `backend/agents/chat.py` 1410–1488：text content 和 tool_calls 分别累加
- 真 tool_calls 在 `tool_calls_acc` dict，单独 dispatch 给 `_execute_tool`
- **结论：sanitize content 不会动到真 tool calls，零误伤风险**

**B. Fallback tool calling（LLM 把 XML/JSON 喂进 content）**
- Qwen / Anthropic-style 把 `<tool_call>...` / `<function_calls>...` / ` ```json{...}``` ` /
  `<netease.daily_recommend>` 等写到 `delta.content`
- `backend/agents/tool_call_resilience.py` 在流结束后扫 full_reply 配 4 条 regex 真执行 +
  剥 XML 残骸，返回 `(cleaned_text, executed)`
- 这是 fallback，capability 副作用还是真生效的——只是文本要剥干净

**核心区分**：通道 A 的 tool_calls 是结构化字段，sanitize 完全不接触；通道 B 的 fallback
和 LLM hallucinated tag 在文本上**长得一样**——区别是命中已知 capability name 则是 B
（真 tool），不命中则纯属 hallucinate（要剥）。本 bugfix 处理的是 hallucinated 部分。

## 2. 现有 sanitize 状态

`backend/utils/text_filters.py` 已是 5 道 strip 链 + 通用 SUSPICIOUS 兜底：

| Stripper                       | 覆盖                                                 |
| ------------------------------ | ---------------------------------------------------- |
| `strip_thinking`               | `<thinking>...</thinking>`                           |
| `strip_emotion`                | `<emotion>X</emotion>` + `<emotion/>`                |
| `strip_state_update`           | `<state_update ... />` + 容错配对                    |
| `strip_motion`                 | `<motion>X</motion>` + 自闭合                        |
| `strip_tool_call_fallback`     | `<tool_call>` / `<function_calls>` / `<invoke>` /     |
|                                | ` ```json{...}``` ` / `<cap.name>...</cap.name>`     |
| `sanitize_suspicious_tags`     | 通用 `<name>...</name>` + `<name/>` 兜底（白名单思路）|

**集成点**（all 3 道已就位）：
- `chat.py` 流式按段 parse + emit（emotion / state_update / thinking / motion）
- `ws.py` 写库前 + text_chunk 发 FE 前（`strip_all_for_tts` line 1018）
- `tts/__init__.py:85` synthesize 前 `strip_all_for_tts` 兜底

## 3. 泄露 case 分析（用户实测：`<docx.create(...)>`）

```
<docx.create(filename="MomoOS_测试漏洞记录", title="...", paragraphs=[...])>
```

这是 LLM hallucinated 的 **Python 函数调用语法包在 angle bracket 里**——既不
self-close（无 `/>`）也无 paired close tag（`</docx.create>` 不存在）。

逐个验证现有 regex 为何**漏**：

| Regex                           | 失败原因                                              |
| ------------------------------- | ----------------------------------------------------- |
| `_STATE_UPDATE_RE`              | tag name 不是 `state_update`                          |
| capability-as-tag（含 `.` 那条）| `(?:\s+[^>]*?)?` 要求 attrs 前有空白；这里是 `(` 直接接，且 close 部分要求 `/>` 或 `</docx.create>` |
| `SUSPICIOUS_TAG_RE` paired      | 要求 `</docx.create>` 闭合标签，不存在                |
| `SUSPICIOUS_TAG_RE` self-close  | 要求结尾 `/>`，这里只有 `>`                           |

**所有现有 regex 全部漏**。grep + 真实例验证（脚本）确认。

## 4. 修复策略

新增 `_FUNC_CALL_TAG_RE` 匹配 `<name(args)>` 形态：
```python
r"<[a-z_][a-z_0-9.]*\s*\([^>]*?\)[^>]*?>"
```
- name 允许 `.`（`docx.create`、`netease.daily_recommend`）
- `\([^>]*?\)` 要求紧跟 `(...)` —— 这是与正常 HTML `<a href="...">` 的关键区分点（HTML
  attrs 名后是 `=` 不是 `(`），避免误伤
- 结尾 `>` 但不要求 `/>` 也不要求闭合标签

加进 `_TOOL_CALL_FALLBACK_STRIP_PATTERNS` 列表 → 所有现有 caller（ws.py / TTS / DB 写入
链 / migration）自动覆盖，**零集成点改动**。

额外提供 `sanitize_llm_output(text)` 作 code-block-aware 的全套入口：
1. 临时替换 `` `inline code` `` / ` ```fenced``` ` 为 placeholder（保护用户引用合法 tag）
2. 跑全套 strip 链 + 新 `_FUNC_CALL_TAG_RE` + SUSPICIOUS 兜底
3. 还原 code blocks

## 5. 设计决策

- **不剥裸函数调用** `docx.create(args=...)`（无 angle bracket）—— 太容易误伤普通文本里
  正经的函数引用 / 代码描述。要求必须有 `<` `>` 包裹才剥。
- **保留通道 A**：sanitize 只跑在 `delta.content` / 文本流，永远不接触
  `tool_calls_acc` 结构化字段。
- **保护 markdown 代码段**：inline `` ` `` 和 fenced ``` ``` ``` 内合法 `<thinking>` 等
  引用不剥（用户讲解 / 文档场景）。
- **加入 `_TOOL_CALL_FALLBACK_STRIP_PATTERNS` 而非另开 list**：复用所有现有 caller，
  diff 最小，未来扩展也走同一处。

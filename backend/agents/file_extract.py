"""2026-06-19 · 文件输入 MVP · 后端文件 → 文本抽取单入口分派。

跟 image 链共栈:ws.py 收 attachments[{kind:'file', filename, mime, data_url}]
→ chat.py::_user_content 调本模块 extract_text → 拼 "[文件 {filename}]\\n{text}"
进 user content text block。

支持(白名单 · 锁定 2):
- 纯文本 / markdown / 代码后缀 → utf-8 decode(errors='replace')
- .docx → python-docx 段落 join
- .pdf  → pypdf 逐页 extract_text join

不支持(spec 标限制):
- 扫描件 / 纯图片型 PDF(返空 + 标记 source='pdf' empty=True)
- pptx / xlsx / doc(旧) / rtf(不在白名单)
- 加密 / 损坏文件(catch + 返空 + error 字段)

mime 不可信兜底(补丁 B):mime 失配时按 filename 扩展名路由。
"""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

# 抽出文本上限 ≈ 12k tokens(中英文混算)· 截断 + 末尾标注
# 中文 1 字 ≈ 1.5 token / 英文 1 字 ≈ 0.25 token · 48k 字符是个保守上限
MAX_EXTRACTED_CHARS = 48_000
TRUNCATION_MARKER = "\n[文件较长 · 已截断]"

# mime 白名单(锁定 2)· 一致校验跟 ws.py 守门同源
TEXT_MIMES = frozenset({
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/json",
    "application/x-yaml",
    "text/yaml",
    "text/x-yaml",
    "text/csv",
    "text/html",
    "text/css",
    "application/xml",
    "text/xml",
})
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"

# 代码 / 文本扩展名白名单(补丁 B · mime 不可信时按扩展兜底)
CODE_TEXT_EXTS = frozenset({
    "txt", "md", "markdown", "rst",
    "py", "ts", "tsx", "js", "jsx", "mjs", "cjs",
    "json", "yaml", "yml", "toml", "ini", "cfg", "conf",
    "sh", "bash", "zsh", "fish",
    "html", "htm", "css", "scss", "sass", "less",
    "go", "rs", "java", "kt", "swift",
    "c", "cpp", "cc", "cxx", "h", "hpp",
    "rb", "php", "lua", "pl", "r",
    "sql", "csv", "tsv", "xml", "log",
    "vue", "svelte", "tex",
    "env", "gitignore", "dockerignore",
})


def _ext_of(filename: str) -> str:
    """Lowercase extension without dot · 无扩展名返空串。"""
    name = PurePosixPath(filename or "").name
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower()


def is_supported(mime: str | None, filename: str | None) -> bool:
    """ws.py 守门用 · mime 白名单 OR 扩展名白名单(补丁 B)。

    docx / pdf 必须 mime 准(浏览器对这俩通常返对的 mime)。
    text/code 类 mime 失配时按扩展兜底放行。
    """
    m = (mime or "").lower()
    if m == DOCX_MIME or m == PDF_MIME:
        return True
    if m in TEXT_MIMES:
        return True
    ext = _ext_of(filename or "")
    if ext in CODE_TEXT_EXTS:
        return True
    return False


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EXTRACTED_CHARS:
        return text, False
    return text[:MAX_EXTRACTED_CHARS] + TRUNCATION_MARKER, True


def _extract_text_utf8(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _extract_docx(data: bytes) -> str:
    from docx import Document  # noqa: PLC0415
    doc = Document(BytesIO(data))
    parts: list[str] = []
    for para in doc.paragraphs:
        t = para.text
        if t:
            parts.append(t)
    # 表格 / 图片 / 公式 MVP 不读(spec 标限制)
    return "\n".join(parts)


def _extract_pdf(data: bytes) -> tuple[str, int]:
    """返 (text, empty_pages_count)· 扫描件 / 纯图片型 → text 为空 + 高 empty。"""
    from pypdf import PdfReader  # noqa: PLC0415
    reader = PdfReader(BytesIO(data))
    pages: list[str] = []
    empty_pages = 0
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        if t.strip():
            pages.append(t)
        else:
            empty_pages += 1
    return "\n\n".join(pages), empty_pages


def extract_text(
    filename: str, mime: str | None, data: bytes,
) -> tuple[str, dict]:
    """单入口 · 返 (text, meta)。

    meta = {
        source: 'utf-8' | 'docx' | 'pdf' | 'unknown',
        truncated: bool,
        bytes: int,
        empty: bool,        # 抽空(扫描件 PDF / 纯空文档)
        error: str | None,  # 抽取失败时填(catch 后)
    }

    抽取失败一律返 ('', meta_with_error)· 不抛 · 让 _user_content 拼时透明给 LLM。
    """
    meta: dict = {
        "source": "unknown",
        "truncated": False,
        "bytes": len(data),
        "empty": False,
        "error": None,
    }
    m = (mime or "").lower()
    ext = _ext_of(filename or "")

    try:
        # docx / pdf 优先按 mime
        if m == DOCX_MIME or ext == "docx":
            meta["source"] = "docx"
            text = _extract_docx(data)
        elif m == PDF_MIME or ext == "pdf":
            meta["source"] = "pdf"
            text, empty_pages = _extract_pdf(data)
            if empty_pages > 0:
                meta["empty_pages"] = empty_pages
        elif m in TEXT_MIMES or ext in CODE_TEXT_EXTS:
            meta["source"] = "utf-8"
            text = _extract_text_utf8(data)
        else:
            # 兜底:utf-8 试一把(很多代码文件 mime 是 octet-stream)
            meta["source"] = "utf-8"
            text = _extract_text_utf8(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[file_extract] failed filename=%s mime=%s source=%s: %s",
            filename, mime, meta["source"], exc,
        )
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return "", meta

    if not text.strip():
        meta["empty"] = True
        return "", meta

    text, truncated = _truncate(text)
    meta["truncated"] = truncated
    return text, meta

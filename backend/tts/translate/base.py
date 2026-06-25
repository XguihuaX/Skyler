"""TranslateProvider — 翻译 provider 抽象基类。

新增 provider(如火山翻译)实现此接口 + 在 translate/__init__.py 注册即可。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class TranslateProvider(ABC):
    @abstractmethod
    async def translate(self, text: str, src: str, dst: str) -> str:
        """翻译 text 从 src 语种到 dst 语种，返回翻译后文本。失败时抛 Exception。

        Args:
            text: 源文本(纯文本,不含 HTML/XML tag)。
            src: 源语种代码,本模块内部已统一为 ISO-639-1('zh'/'ja'/'en')。
            dst: 目标语种代码,同上。
        """

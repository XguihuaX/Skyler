from abc import ABC, abstractmethod
from typing import AsyncGenerator


class IAgent(ABC):
    @abstractmethod
    async def handle(self, message: dict) -> dict:
        """非流式处理，返回结果 dict"""
        ...

    async def stream(self, message: dict) -> AsyncGenerator[str, None]:
        """流式处理，默认不支持，子类可覆盖"""
        raise NotImplementedError
        yield  # make it a generator

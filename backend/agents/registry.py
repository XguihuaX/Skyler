from typing import Dict, Type

from backend.agents.base import IAgent


class AgentRegistry:
    _registry: Dict[str, IAgent] = {}

    @classmethod
    def register(cls, name: str, agent: IAgent) -> None:
        cls._registry[name] = agent

    @classmethod
    def get(cls, name: str) -> IAgent:
        if name not in cls._registry:
            raise KeyError(f"Agent '{name}' not registered")
        return cls._registry[name]

    @classmethod
    def list_agents(cls) -> list[str]:
        return list(cls._registry.keys())

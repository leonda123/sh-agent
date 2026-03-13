from typing import Dict, Optional, List
from app.core.base_agent import BaseAgent
import importlib
import pkgutil
import os

class AgentManager:
    _instance = None
    _agents: Dict[str, BaseAgent] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentManager, cls).__new__(cls)
            cls._instance._load_agents()
        return cls._instance

    def _load_agents(self):
        """
        Dynamically load agents from the 'agents' directory.
        For now, we manually register known agents to be safe, 
        or we can implement auto-discovery.
        Let's start with manual registration for simplicity and reliability.
        """
        # Manual registration
        from agents.doc_audit.agent import DocAuditAgent
        self.register_agent(DocAuditAgent())

    def register_agent(self, agent: BaseAgent):
        if agent.name in self._agents:
            print(f"Warning: Agent {agent.name} already registered. Overwriting.")
        self._agents[agent.name] = agent
        print(f"Registered agent: {agent.name}")

    def get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        return self._agents.get(agent_name)

    def list_agents(self) -> List[Dict[str, str]]:
        return [
            {
                "id": agent.name,
                "name": agent.display_name,
                "description": agent.description
            }
            for agent in self._agents.values()
        ]

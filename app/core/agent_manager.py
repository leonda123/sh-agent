from typing import Dict, Optional, List
from app.core.base_agent import BaseAgent
import importlib.util
import os
import sys

class AgentManager:
    """
    智能体管理器，负责智能体的自动发现、注册和检索。
    这是一个单例类，确保系统中只有一个管理器实例。
    """
    _instance = None
    _agents: Dict[str, BaseAgent] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentManager, cls).__new__(cls)
            cls._instance._load_agents()
        return cls._instance

    def _load_agents(self):
        """
        动态加载 'agents' 目录下的所有智能体。
        """
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        agents_dir = os.path.join(project_root, "agents")

        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        
        if not os.path.exists(agents_dir):
            print(f"Warning: Agents directory not found at {agents_dir}")
            return

        print(f"Scanning for agents in {agents_dir}...")
        
        for agent_file in self._iter_agent_files(agents_dir):
            relative_path = os.path.relpath(agent_file, agents_dir)
            module_path = os.path.splitext(relative_path)[0].replace(os.sep, ".")
            module_name = f"agents.{module_path}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, agent_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    
                    # 查找 BaseAgent 的子类
                    found_agent = False
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        # 检查是否是类，是否继承自 BaseAgent，且不是 BaseAgent 本身
                        if (isinstance(attr, type) and 
                            issubclass(attr, BaseAgent) and 
                            attr is not BaseAgent):
                            
                            # 实例化并注册
                            try:
                                agent_instance = attr()
                                self.register_agent(agent_instance)
                                found_agent = True
                                # 每个文件只注册一个智能体，避免重复
                                break 
                            except Exception as e:
                                print(f"Failed to instantiate agent {attr_name} in {relative_path}: {e}")
                    
                    if not found_agent:
                        print(f"No BaseAgent subclass found in {agent_file}")
                        
            except Exception as e:
                print(f"Failed to load agent module {relative_path}: {e}")

    def _iter_agent_files(self, agents_dir: str) -> List[str]:
        agent_files: List[str] = []
        for root, dir_names, file_names in os.walk(agents_dir):
            dir_names[:] = [
                directory
                for directory in dir_names
                if not directory.startswith("__") and not directory.startswith(".")
            ]
            if "agent.py" in file_names:
                agent_files.append(os.path.join(root, "agent.py"))
        return sorted(agent_files)

    def register_agent(self, agent: BaseAgent):
        """
        注册一个智能体实例。
        """
        if agent.name in self._agents:
            print(f"Warning: Agent {agent.name} already registered. Overwriting.")
        self._agents[agent.name] = agent
        print(f"Registered agent: {agent.name} ({agent.display_name})")

    def get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """
        根据名称获取智能体实例。
        """
        return self._agents.get(agent_name)

    def list_agents(self) -> List[Dict[str, object]]:
        """
        列出所有已注册的智能体信息。
        """
        return [
            {
                "id": agent.name,
                "name": agent.display_name,
                "description": agent.description,
                "category_folder": agent.category_folder,
                "category_name": agent.category_name,
                "checklist_items": agent.checklist_items,
                "min_file_count": agent.min_file_count,
                "max_file_count": agent.max_file_count,
                "accepts_multiple_files": agent.accepts_multiple_files,
                "phase_definitions": agent.phase_definitions,
                "phase_task_requirements": agent.phase_task_requirements,
                "role_phase_map": agent.role_phase_map,
            }
            for agent in self._agents.values()
        ]

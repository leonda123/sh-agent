from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from queue import Queue
from threading import Event

class BaseAgent(ABC):
    """
    Abstract base class for all agents in the platform.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for the agent (e.g., 'doc_audit').
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable name for the agent (e.g., '文档图表一致性审计').
        """
        pass
        
    @property
    @abstractmethod
    def description(self) -> str:
        """
        Short description of what the agent does.
        """
        pass

    @abstractmethod
    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        """
        Execute the agent logic.
        
        :param inputs: Input data for the agent (e.g., file_path, user_query).
        :param queue: Queue to push events to (for streaming to frontend).
        :param stop_event: Event to check for cancellation requests.
        :return: Final result of the agent execution.
        """
        pass

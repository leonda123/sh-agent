from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from queue import Queue
from threading import Event

class BaseAgent(ABC):
    """
    平台中所有智能体的抽象基类。
    所有新开发的智能体都必须继承此类并实现其抽象方法。
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        智能体的唯一标识符 (例如: 'doc_audit')。
        建议使用英文小写字母和下划线。
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        智能体的人类可读名称 (例如: '文档图表一致性审计')。
        这将显示在前端界面上。
        """
        pass
        
    @property
    @abstractmethod
    def description(self) -> str:
        """
        智能体功能的简短描述。
        用于告知用户该智能体的用途。
        """
        pass

    @abstractmethod
    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        """
        执行智能体的核心业务逻辑。
        
        :param inputs: 智能体的输入数据 (例如: file_path, user_query)。
        :param queue: 消息队列，用于向前端推送实时事件 (流式传输)。
        :param stop_event: 停止事件对象，用于检查是否有取消请求。
        :return: 智能体执行的最终结果。
        """
        pass

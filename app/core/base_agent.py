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

    @property
    def min_file_count(self) -> int:
        return 1

    @property
    def max_file_count(self) -> Optional[int]:
        return 1

    @property
    def accepts_multiple_files(self) -> bool:
        return self.max_file_count is None or self.max_file_count > 1

    @property
    def phase_definitions(self) -> List[Dict[str, str]]:
        return [
            {"id": "phase_1", "label": "阶段一"},
            {"id": "phase_2", "label": "阶段二"},
            {"id": "phase_3", "label": "阶段三"},
        ]

    @property
    def phase_task_requirements(self) -> Dict[str, int]:
        return {
            phase["id"]: 1
            for phase in self.phase_definitions
        }

    @property
    def role_phase_map(self) -> Dict[str, str]:
        return {}

    @property
    def category_folder(self) -> str:
        return ""

    @property
    def category_name(self) -> str:
        return ""

    @property
    def checklist_items(self) -> List[Dict[str, str]]:
        return []

    def get_input_files(self, inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        files = inputs.get("files")
        if files:
            return files

        file_path = inputs.get("file_path")
        if not file_path:
            return []

        return [
            {
                "name": inputs.get("file_name"),
                "path": file_path,
                "content_type": inputs.get("content_type"),
            }
        ]

    def validate_file_inputs(self, inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        files = self.get_input_files(inputs)
        file_count = len(files)

        if file_count < self.min_file_count:
            raise ValueError(f"{self.display_name} 至少需要上传 {self.min_file_count} 个文件。")

        if self.max_file_count is not None and file_count > self.max_file_count:
            raise ValueError(f"{self.display_name} 最多只支持 {self.max_file_count} 个文件，当前上传了 {file_count} 个。")

        return files

    def get_primary_input_file(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        files = self.validate_file_inputs(inputs)
        return files[0]

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

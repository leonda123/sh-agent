import json
import os
import time
from typing import List, Dict, Any, Optional
from datetime import datetime

class HistoryManager:
    """
    历史记录管理器，负责持久化会话数据和事件日志。
    目前使用简单的 JSON 文件存储。
    """
    def __init__(self, storage_dir: str = "storage/sessions"):
        """
        初始化历史管理器。
        :param storage_dir: 存储会话文件的目录路径。
        """
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def _get_file_path(self, session_id: str) -> str:
        """根据会话 ID 获取对应的文件路径。"""
        return os.path.join(self.storage_dir, f"{session_id}.json")

    def create_session(self, session_id: str, agent_id: str, file_name: str) -> Dict[str, Any]:
        """
        创建一个新的会话记录。
        :param session_id: 会话 ID
        :param agent_id: 智能体 ID
        :param file_name: 原始文件名
        :return: 创建的会话数据字典
        """
        session_data = {
            "session_id": session_id,
            "agent_id": agent_id,
            "file_name": file_name,
            "start_time": time.time(),
            "end_time": None,
            "status": "running", # running, completed, failed, stopped
            "events": [], # 事件日志列表
            "result": None
        }
        self.save_session(session_id, session_data)
        return session_data

    def save_session(self, session_id: str, data: Dict[str, Any]):
        """
        保存会话数据到文件。
        """
        with open(self._get_file_path(session_id), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取会话详情。
        """
        path = self._get_file_path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有历史会话的摘要信息，按开始时间倒序排列。
        """
        sessions = []
        if not os.path.exists(self.storage_dir):
            return []
            
        for filename in os.listdir(self.storage_dir):
            if filename.endswith('.json'):
                path = os.path.join(self.storage_dir, filename)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # 返回摘要信息
                        sessions.append({
                            "session_id": data.get("session_id"),
                            "agent_id": data.get("agent_id"),
                            "file_name": data.get("file_name"),
                            "start_time": data.get("start_time"),
                            "end_time": data.get("end_time"),
                            "status": data.get("status")
                        })
                except Exception:
                    continue
        
        # 按 start_time 倒序排列
        sessions.sort(key=lambda x: x.get("start_time", 0), reverse=True)
        return sessions

    def append_event(self, session_id: str, event: Dict[str, Any]):
        """
        向指定会话追加一个事件日志，并更新会话状态。
        注意：目前实现为读取-修改-写入整个文件，对于高并发或大数据量可能存在性能瓶颈。
        """
        session = self.get_session(session_id)
        if session:
            session["events"].append({
                "timestamp": time.time(),
                "event": event
            })
            
            # 如果是终止事件，更新状态
            if event.get("type") == "result":
                session["status"] = "completed"
                session["end_time"] = time.time()
                session["result"] = event.get("data")
            elif event.get("type") == "error":
                session["status"] = "failed"
                session["end_time"] = time.time()
            elif event.get("type") == "stop":
                session["status"] = "stopped"
                session["end_time"] = time.time()
                
            self.save_session(session_id, session)

history_manager = HistoryManager()

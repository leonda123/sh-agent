import json
import os
import time
import uuid
import threading
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
        self._locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, session_id: str) -> threading.RLock:
        """获取指定会话的线程锁，确保并发读写安全"""
        with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = threading.RLock()
            return self._locks[session_id]

    def _replace_with_retry(self, src: str, dst: str, retries: int = 5, delay: float = 0.1):
        """带有重试机制的原子替换，避免 Windows 下文件被短暂占用导致的 WinError 32"""
        for i in range(retries):
            try:
                os.replace(src, dst)
                return
            except OSError as e:
                if i == retries - 1:
                    raise e
                time.sleep(delay)

    def _get_file_path(self, session_id: str) -> str:
        """根据会话 ID 获取对应的文件路径。"""
        return os.path.join(self.storage_dir, f"{session_id}.json")

    def create_session(self, session_id: str, agent_id: str, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        创建一个新的会话记录。
        :param session_id: 会话 ID
        :param agent_id: 智能体 ID
        :param files: 上传文件元数据列表
        :return: 创建的会话数据字典
        """
        file_names = [item.get("name") for item in files if item.get("name")]
        file_count = len(file_names)
        display_file_name = "unknown"
        if file_count == 1:
            display_file_name = file_names[0]
        elif file_count > 1:
            display_file_name = f"{file_names[0]} 等 {file_count} 个文件"

        session_data = {
            "session_id": session_id,
            "agent_id": agent_id,
            "file_name": display_file_name,
            "file_names": file_names,
            "file_count": file_count,
            "files": files,
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
        保存会话数据到文件。使用原子写入以防止文件损坏。
        """
        with self._get_lock(session_id):
            try:
                # 使用带有 uuid 的临时文件以防止并发写同一个临时文件
                temp_path = self._get_file_path(session_id) + f".{uuid.uuid4().hex}.tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self._replace_with_retry(temp_path, self._get_file_path(session_id))
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to save session {session_id}: {e}")
                # 清理可能的临时文件
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取会话详情。
        """
        with self._get_lock(session_id):
            path = self._get_file_path(session_id)
            if not os.path.exists(path):
                return None
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to load session {session_id} from {path}: {e}")
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
                session_id = filename[:-5]
                path = os.path.join(self.storage_dir, filename)
                with self._get_lock(session_id):
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            # 返回摘要信息
                            sessions.append({
                                "session_id": data.get("session_id"),
                                "agent_id": data.get("agent_id"),
                                "file_name": data.get("file_name"),
                                "file_names": data.get("file_names", []),
                                "file_count": data.get("file_count", 1),
                                "start_time": data.get("start_time"),
                                "end_time": data.get("end_time"),
                                "status": data.get("status")
                            })
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"Failed to load session from {path} in list_sessions: {e}")
                        continue
        
        # 按 start_time 倒序排列
        sessions.sort(key=lambda x: x.get("start_time", 0), reverse=True)
        return sessions

    def append_event(self, session_id: str, event: Dict[str, Any]):
        """
        向指定会话追加一个事件日志，并更新会话状态。
        注意：目前实现为读取-修改-写入整个文件，对于高并发或大数据量可能存在性能瓶颈。
        """
        with self._get_lock(session_id):
            session = self.get_session(session_id)
            if not session:
                # 如果文件已存在但解析失败（可能是 JSON 损坏），我们可以尝试从文件中恢复基本信息
                path = self._get_file_path(session_id)
                if os.path.exists(path):
                    try:
                        # 尝试恢复基本信息，避免完全丢失会话
                        # 这只是一个后备方案，如果文件严重损坏可能仍无法完全恢复
                        session = {
                            "session_id": session_id,
                            "agent_id": "unknown",
                            "file_name": "unknown",
                            "file_names": ["unknown"],
                            "file_count": 1,
                            "files": [],
                            "start_time": time.time(),
                            "end_time": None,
                            "status": "running",
                            "events": [],
                            "result": None
                        }
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Session file {path} might be corrupted, re-initializing session data.")
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"Failed to recover session {session_id}: {e}")
                        return
                else:
                    return

            session.setdefault("events", []).append({
                "timestamp": time.time(),
                "event": event
            })

            # 根据事件类型更新状态
            event_type = event.get("type")
            if event_type == "result":
                session["status"] = "completed"
                session["end_time"] = time.time()
                session["result"] = event.get("data")
            elif event_type == "error":
                session["status"] = "failed"
                session["end_time"] = time.time()
                session["result"] = event.get("message")
            elif event_type == "stop":
                session["status"] = "stopped"
                session["end_time"] = time.time()

            # 复用 save_session 进行安全保存
            self.save_session(session_id, session)

history_manager = HistoryManager()

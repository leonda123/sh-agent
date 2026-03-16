import json
import os
import time
from typing import List, Dict, Any, Optional
from datetime import datetime

class HistoryManager:
    def __init__(self, storage_dir: str = "storage/sessions"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def _get_file_path(self, session_id: str) -> str:
        return os.path.join(self.storage_dir, f"{session_id}.json")

    def create_session(self, session_id: str, agent_id: str, file_name: str) -> Dict[str, Any]:
        session_data = {
            "session_id": session_id,
            "agent_id": agent_id,
            "file_name": file_name,
            "start_time": time.time(),
            "end_time": None,
            "status": "running", # running, completed, failed, stopped
            "events": [], # List of log events
            "result": None
        }
        self.save_session(session_id, session_data)
        return session_data

    def save_session(self, session_id: str, data: Dict[str, Any]):
        with open(self._get_file_path(session_id), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_file_path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        sessions = []
        if not os.path.exists(self.storage_dir):
            return []
            
        for filename in os.listdir(self.storage_dir):
            if filename.endswith('.json'):
                path = os.path.join(self.storage_dir, filename)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Return summary info
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
        
        # Sort by start_time desc
        sessions.sort(key=lambda x: x.get("start_time", 0), reverse=True)
        return sessions

    def append_event(self, session_id: str, event: Dict[str, Any]):
        # To avoid reading/writing the whole file for every event, 
        # we could use a separate .jsonl file for events, 
        # but for simplicity and low volume, we'll read-modify-write for now.
        # Optimization: In-memory cache could be used in production.
        session = self.get_session(session_id)
        if session:
            session["events"].append({
                "timestamp": time.time(),
                "event": event
            })
            
            # Update status if terminal event
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

import logging
import json
import asyncio
import time
from queue import Queue, Empty
from threading import Thread, Event
from typing import Dict, Any, Optional
from contextvars import ContextVar
import litellm

from app.core.agent_manager import AgentManager
from app.core.history import HistoryManager

# 配置日志记录器
logger = logging.getLogger(__name__)

# 全局状态，用于存储活动会话
# 键为会话ID，值为对应的队列或事件对象
session_queues: Dict[str, Queue] = {}
session_events: Dict[str, Event] = {}

# 线程本地存储上下文变量
# 用于在 LiteLLM 回调中访问当前会话的 token 使用情况和队列
session_usage = ContextVar('session_usage', default=None)
session_queue = ContextVar('session_queue', default=None)

# 实例化历史管理器
history_manager = HistoryManager()

def litellm_callback(kwargs, completion_response, start_time, end_time):
    """
    LiteLLM 的回调函数，用于跟踪 Token 使用情况并捕获 LLM 交互内容。
    """
    try:
        # 1. 跟踪 Token 使用情况
        usage = session_usage.get()
        if usage is not None and 'usage' in completion_response:
            u = completion_response['usage']
            usage['total_tokens'] += u.get('total_tokens', 0)
            usage['prompt_tokens'] += u.get('prompt_tokens', 0)
            usage['completion_tokens'] += u.get('completion_tokens', 0)
            
        # 2. 捕获 LLM 交互 (输入/输出)
        queue = session_queue.get()
        if queue is not None:
            # 提取输入 (消息列表)
            input_messages = kwargs.get('messages', [])
            
            # 提取输出 (内容)
            output_content = ""
            if 'choices' in completion_response and len(completion_response['choices']) > 0:
                message = completion_response['choices'][0].get('message', {})
                output_content = message.get('content', "")
            
            # 提取模型名称
            model = kwargs.get('model', 'unknown')
            
            # 从系统提示词中提取智能体名称
            agent_name = "Unknown Agent"
            if len(input_messages) > 0 and input_messages[0].get('role') == 'system':
                content = input_messages[0].get('content', '')
                import re
                match = re.search(r"You are (.*?)(?:\.|,|\n)", content)
                if match:
                    agent_name = match.group(1).strip()
                else:
                    match = re.search(r"Your role is (.*?)(?:\.|,|\n)", content)
                    if match:
                        agent_name = match.group(1).strip()
            
            # 推送到队列
            queue.put({
                "type": "llm_io",
                "data": {
                    "input": input_messages,
                    "output": output_content,
                    "model": model,
                    "agent": agent_name
                }
            })
            
    except Exception:
        # 忽略上下文错误 (例如从我们管理的上下文之外调用)
        pass

# 注册回调函数到 LiteLLM
if litellm_callback not in litellm.success_callback:
    litellm.success_callback.append(litellm_callback)

class HistoryQueue:
    """
    Queue 的包装类，用于自动将事件持久化到历史记录中。
    """
    def __init__(self, queue: Queue, session_id: str, history_manager: HistoryManager):
        self.queue = queue
        self.session_id = session_id
        self.history_manager = history_manager

    def put(self, item, block=True, timeout=None):
        """将项目放入队列并保存到历史记录。"""
        self.queue.put(item, block, timeout)
        # 持久化到历史
        try:
            self.history_manager.append_event(self.session_id, item)
        except Exception as e:
            logger.error(f"Failed to persist event to history: {e}")

    def get(self, block=True, timeout=None):
        """从队列中获取项目。"""
        return self.queue.get(block, timeout)

    def get_nowait(self):
        """非阻塞地从队列中获取项目。"""
        return self.queue.get_nowait()
    
    def empty(self):
        """检查队列是否为空。"""
        return self.queue.empty()

def _run_agent_in_background(agent_id: str, session_id: str, inputs: dict, queue: Queue, stop_event: Event):
    """
    内部函数：在后台线程中运行智能体流程。
    """
    # 包装队列以持久化事件
    history_queue = HistoryQueue(queue, session_id, history_manager)

    # 初始化当前会话的使用统计
    usage_stats = {'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
    
    # 设置当前线程的上下文变量
    token_usage = session_usage.set(usage_stats)
    token_queue = session_queue.set(history_queue) # 使用包装后的队列
    
    try:
        # 1. 发送开始事件
        history_queue.put({"type": "start", "message": f"Agent {agent_id} started."})
        
        # 2. 获取智能体实例
        manager = AgentManager()
        agent = manager.get_agent(agent_id)
        if not agent:
             history_queue.put({"type": "error", "message": f"Agent {agent_id} not found."})
             return

        # 3. 执行智能体
        result = agent.run(inputs, history_queue, stop_event)
        
        # 4. 发送结果事件
        if not stop_event.is_set():
            # 如果结果是 CrewOutput，获取原始字符串
            if hasattr(result, 'raw'):
                 final_output = result.raw
            else:
                 final_output = str(result)
                 
            history_queue.put({
                "type": "result", 
                "data": final_output,
                "usage": usage_stats
            })
            
    except Exception as e:
        logger.error(f"Error in background task: {e}", exc_info=True)
        history_queue.put({"type": "error", "message": str(e)})
    finally:
        # 清理上下文变量
        session_usage.reset(token_usage)
        session_queue.reset(token_queue)
        # 发送 None 以结束流式传输
        queue.put(None)

class AgentRunner:
    """
    Facade 类，用于管理智能体执行、历史记录和后台处理。
    """
    
    @staticmethod
    def start_agent(agent_id: str, inputs: dict, session_id: str, files: list[dict]):
        """
        在后台线程中启动一个智能体。
        """
        # 在历史记录中创建会话
        history_manager.create_session(session_id, agent_id, files)
        
        # 创建队列和停止事件
        queue = Queue()
        stop_event = Event()
        session_queues[session_id] = queue
        session_events[session_id] = stop_event
        
        # 启动后台任务线程
        thread = Thread(
            target=_run_agent_in_background,
            args=(agent_id, session_id, inputs, queue, stop_event)
        )
        thread.start()
        
        return session_id

    @staticmethod
    def stop_session(session_id: str) -> bool:
        """
        停止正在运行的会话。如果会话存在并被停止，返回 True。
        """
        if session_id in session_events:
            session_events[session_id].set()
            
            if session_id in session_queues:
                msg = {"type": "stop", "message": "Session stopped by user."}
                session_queues[session_id].put(msg)
                history_manager.append_event(session_id, msg)
            return True
        return False

    @staticmethod
    def get_queue(session_id: str) -> Optional[Queue]:
        """
        获取会话的事件队列。
        """
        return session_queues.get(session_id)

    @staticmethod
    def get_history_manager() -> HistoryManager:
        """
        返回历史管理器实例。
        """
        return history_manager

    @staticmethod
    def list_agents():
        """
        列出所有可用的智能体。
        """
        manager = AgentManager()
        return manager.list_agents()

from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
import shutil
import os
import uuid
import logging
import json
import asyncio
import time
from queue import Queue, Empty
from threading import Thread, Event
from app.core.agent_manager import AgentManager
import litellm
from contextvars import ContextVar

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from app.core.history import HistoryManager

router = APIRouter()
history_manager = HistoryManager()

# Store active sessions and their event queues
# Key: session_id, Value: Queue
session_queues = {}
# Key: session_id, Value: Event (for stopping execution)
session_events = {}

# Context var to hold the usage dict for the current thread/context
session_usage = ContextVar('session_usage', default=None)
# Context var to hold the queue for the current thread/context
session_queue = ContextVar('session_queue', default=None)

def litellm_callback(kwargs, completion_response, start_time, end_time):
    """Callback for LiteLLM to track token usage and capture LLM interaction."""
    try:
        # 1. Track Usage
        usage = session_usage.get()
        if usage is not None and 'usage' in completion_response:
            u = completion_response['usage']
            usage['total_tokens'] += u.get('total_tokens', 0)
            usage['prompt_tokens'] += u.get('prompt_tokens', 0)
            usage['completion_tokens'] += u.get('completion_tokens', 0)
            
        # 2. Capture LLM Interaction (Input/Output)
        queue = session_queue.get()
        if queue is not None:
            # Extract Input (Messages)
            input_messages = kwargs.get('messages', [])
            
            # Extract Output (Content)
            output_content = ""
            if 'choices' in completion_response and len(completion_response['choices']) > 0:
                message = completion_response['choices'][0].get('message', {})
                output_content = message.get('content', "")
            
            # Extract Model
            model = kwargs.get('model', 'unknown')
            
            # Extract Agent Name from System Prompt
            agent_name = "Unknown Agent"
            if len(input_messages) > 0 and input_messages[0].get('role') == 'system':
                content = input_messages[0].get('content', '')
                # Simple heuristic: CrewAI prompts usually start with "You are [Role]."
                # or contain "Your role is [Role]"
                import re
                match = re.search(r"You are (.*?)(?:\.|,|\n)", content)
                if match:
                    agent_name = match.group(1).strip()
                else:
                    # Fallback: check for "Your role is"
                    match = re.search(r"Your role is (.*?)(?:\.|,|\n)", content)
                    if match:
                        agent_name = match.group(1).strip()
            
            # Push to queue
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
        # Ignore context errors (e.g. called from outside our managed context)
        pass

# Register callback
if litellm_callback not in litellm.success_callback:
    litellm.success_callback.append(litellm_callback)

class HistoryQueue:
    """Wrapper around Queue to persist events to history."""
    def __init__(self, queue: Queue, session_id: str, history_manager: HistoryManager):
        self.queue = queue
        self.session_id = session_id
        self.history_manager = history_manager

    def put(self, item, block=True, timeout=None):
        self.queue.put(item, block, timeout)
        # Persist to history
        try:
            self.history_manager.append_event(self.session_id, item)
        except Exception as e:
            logger.error(f"Failed to persist event to history: {e}")

    def get(self, block=True, timeout=None):
        return self.queue.get(block, timeout)

    def get_nowait(self):
        return self.queue.get_nowait()
    
    def empty(self):
        return self.queue.empty()

def run_agent_in_background(agent_id: str, session_id: str, inputs: dict, queue: Queue, stop_event: Event):
    """
    Runs the Agent process in a background thread and pushes events to the queue.
    """
    # Wrap queue to persist events
    history_queue = HistoryQueue(queue, session_id, history_manager)

    # Initialize usage stats for this session
    usage_stats = {'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
    
    # Set context vars for this thread
    token_usage = session_usage.set(usage_stats)
    token_queue = session_queue.set(history_queue) # Use wrapped queue
    
    try:
        # 1. Start Event
        history_queue.put({"type": "start", "message": f"Agent {agent_id} started."})
        
        # 2. Get Agent
        manager = AgentManager()
        agent = manager.get_agent(agent_id)
        if not agent:
             history_queue.put({"type": "error", "message": f"Agent {agent_id} not found."})
             return

        # 3. Execute Agent
        result = agent.run(inputs, history_queue, stop_event)
        
        # 4. Result Event
        if not stop_event.is_set():
            # If result is CrewOutput, get raw string
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
        # Clean up context vars
        session_usage.reset(token_usage)
        session_queue.reset(token_queue)
        pass

@router.get("/agents", summary="获取智能体列表", description="获取系统中所有可用的智能体及其描述。")
async def list_agents():
    """List all available agents."""
    manager = AgentManager()
    return manager.list_agents()

@router.post("/run/{agent_id}", summary="运行智能体", description="上传PDF文件并启动指定的智能体任务。返回会话ID用于追踪进度。", response_description="包含会话ID、状态消息和文件路径的JSON对象。")
async def run_agent(agent_id: str, file: UploadFile = File(...)):
    """
    Upload a file and start the specified agent.
    Returns a session_id to subscribe to SSE updates.
    """
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    # Generate Session ID
    session_id = str(uuid.uuid4())
    
    # Create Upload Directory
    upload_dir = os.path.join("uploads")
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    # Save File
    # Prefix filename with session_id to avoid collisions
    original_filename = os.path.basename(file.filename)
    sanitized_filename = original_filename.replace(" ", "_")
    safe_filename = f"{session_id}_{sanitized_filename}"
    file_path = os.path.join(upload_dir, safe_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Create Session in History
    history_manager.create_session(session_id, agent_id, original_filename)
        
    # Create Queue and Event
    queue = Queue()
    stop_event = Event()
    session_queues[session_id] = queue
    session_events[session_id] = stop_event
    
    # Start Background Task
    thread = Thread(
        target=run_agent_in_background,
        args=(agent_id, session_id, {"file_path": os.path.abspath(file_path)}, queue, stop_event)
    )
    thread.start()
    
    return {
        "session_id": session_id, 
        "message": "Agent started successfully", 
        "file_path": file_path,
        "status": "running",
        "created_at": time.time()
    }

@router.post("/stop/{session_id}", summary="停止任务", description="发送信号停止指定会话的正在运行的任务。")
async def stop_session(session_id: str):
    """
    Stop a running session.
    """
    if session_id in session_events:
        session_events[session_id].set()
        
        if session_id in session_queues:
            # We use the raw queue here, but we should probably use a HistoryQueue wrapper if we want to persist the stop event from here too.
            # But the background thread will handle the stop signal and log "stop" event usually? 
            # Actually, the background thread checks stop_event. 
            # But let's push a stop message to the queue so the frontend gets it immediately.
            # For persistence, we can call history_manager directly.
            
            msg = {"type": "stop", "message": "Session stopped by user."}
            session_queues[session_id].put(msg)
            history_manager.append_event(session_id, msg)
            
        return {"message": "Stop signal sent"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")

@router.get("/stream/{session_id}", summary="监听任务进度 (SSE)", description="通过 Server-Sent Events (SSE) 实时获取任务的执行日志和结果。")
async def stream_audit(session_id: str):
    """
    Streams updates for the given session ID using Server-Sent Events (SSE).
    """
    if session_id not in session_queues:
        # If session not found in active queues, check history?
        # If it's a past session, we can't stream it via this endpoint (it's for live updates).
        # User should use /history/{session_id} for past logs.
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    queue = session_queues[session_id]
    
    async def event_generator():
        # Yield initial connection message
        yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        
        last_activity = time.time()
        
        while True:
            try:
                # Check for new data with non-blocking get
                try:
                    # Use get_nowait to avoid blocking the event loop
                    data = queue.get_nowait()
                    
                    if data is None: # Signal for end of stream
                        break
                    
                    # Reset activity timer on new data
                    last_activity = time.time()
                    
                    # Format as SSE
                    yield f"data: {json.dumps(data)}\n\n"
                    
                    # Check if this is a terminal event
                    if isinstance(data, dict) and data.get("type") in ["result", "error", "stop"]:
                        # We still continue to yield until None is received, 
                        # but usually backend sends None right after.
                        pass
                        
                except Empty:
                    # No data available, yield control to event loop
                    await asyncio.sleep(0.1)
                    
                    # Send keep-alive every 15 seconds
                    if time.time() - last_activity > 15:
                        yield ": keep-alive\n\n"
                        last_activity = time.time()
                        
            except asyncio.CancelledError:
                logger.info(f"Stream cancelled for session {session_id}")
                break
            except Exception as e:
                logger.error(f"Error in event generator: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break
        
        # Cleanup is handled by the background task, not here
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/history", summary="获取历史记录", description="获取所有历史任务会话的列表（按时间倒序）。")
async def list_history():
    """List all historical sessions."""
    return history_manager.list_sessions()

@router.get("/history/{session_id}", summary="获取会话详情", description="获取指定会话的详细信息，包括完整的日志记录。")
async def get_history_session(session_id: str):
    """Get details and logs for a specific session."""
    session = history_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

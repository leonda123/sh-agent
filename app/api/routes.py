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

router = APIRouter()

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

def run_agent_in_background(agent_id: str, session_id: str, inputs: dict, queue: Queue, stop_event: Event):
    """
    Runs the Agent process in a background thread and pushes events to the queue.
    """
    # Initialize usage stats for this session
    usage_stats = {'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
    
    # Set context vars for this thread
    token_usage = session_usage.set(usage_stats)
    token_queue = session_queue.set(queue)
    
    try:
        # 1. Start Event
        queue.put({"type": "start", "message": f"Agent {agent_id} started."})
        
        # 2. Get Agent
        manager = AgentManager()
        agent = manager.get_agent(agent_id)
        if not agent:
             queue.put({"type": "error", "message": f"Agent {agent_id} not found."})
             return

        # 3. Execute Agent
        result = agent.run(inputs, queue, stop_event)
        
        # 4. Result Event
        if not stop_event.is_set():
            # If result is CrewOutput, get raw string
            if hasattr(result, 'raw'):
                 final_output = result.raw
            else:
                 final_output = str(result)
                 
            queue.put({
                "type": "result", 
                "data": final_output,
                "usage": usage_stats
            })
            
    except Exception as e:
        logger.error(f"Error in background task: {e}", exc_info=True)
        queue.put({"type": "error", "message": str(e)})
    finally:
        # Signal completion (important for queue consumer to stop waiting)
        # queue.put(None) # Not strictly needed if consumer handles "result" or "error" as terminal
        # Clean up context vars
        session_usage.reset(token_usage)
        session_queue.reset(token_queue)
        
        # Clean up session resources after a delay to allow frontend to disconnect gracefully
        # or rely on stream_audit cleanup
        pass

@router.get("/agents")
async def list_agents():
    """List all available agents."""
    manager = AgentManager()
    return manager.list_agents()

@router.post("/run/{agent_id}")
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
    
    return {"session_id": session_id, "message": "Agent started", "file_path": file_path}

@router.post("/stop/{session_id}")
async def stop_session(session_id: str):
    """
    Stop a running session.
    """
    if session_id in session_events:
        session_events[session_id].set()
        
        if session_id in session_queues:
            session_queues[session_id].put({"type": "stop", "message": "Session stopped by user."})
            
        return {"message": "Stop signal sent"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")

@router.get("/stream/{session_id}")
async def stream_audit(session_id: str):
    """
    Streams updates for the given session ID using Server-Sent Events (SSE).
    """
    if session_id not in session_queues:
        # If session not found, return 404
        raise HTTPException(status_code=404, detail="Session not found")
    
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
        # to allow multiple clients to potentially connect (though not supported yet)
        # or to allow reconnects if the stream drops but task continues.
        # However, for now, we assume one-time consumption.
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

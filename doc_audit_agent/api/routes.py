from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import shutil
import os
import uuid
import logging
import traceback
import json
import asyncio
import time
from queue import Queue, Empty
from threading import Thread, Event
from doc_audit_agent.core.agents.figure_table_checker.crew import FigureTableCrew
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

def run_crew_in_background(session_id: str, file_path: str, queue: Queue, stop_event: Event):
    """
    Runs the CrewAI process in a background thread and pushes events to the queue.
    """
    # Initialize usage stats for this session
    usage_stats = {'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
    token_usage = session_usage.set(usage_stats)
    token_queue = session_queue.set(queue)

    try:
        logger.info(f"Starting background task for session {session_id}")
        
        # Define callbacks
        def step_callback(step_output):
            # Check if stop requested
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")

            # Send current token usage
            try:
                current_usage = session_usage.get()
                queue.put({
                    "type": "token_usage",
                    "data": current_usage
                })
            except Exception as e:
                logger.error(f"Error sending token usage: {e}")

            # step_output is usually an AgentStep object or similar
            try:
                data = {
                    "type": "step",
                    "content": str(step_output) # Fallback
                }
                
                # Check for agent information
                if hasattr(step_output, 'agent') and step_output.agent:
                     if hasattr(step_output.agent, 'role'):
                         data["agent"] = step_output.agent.role
                     else:
                         data["agent"] = str(step_output.agent)
                
                if hasattr(step_output, 'thought') and step_output.thought:
                     data["thought"] = step_output.thought
                if hasattr(step_output, 'tool') and step_output.tool:
                     data["tool"] = step_output.tool
                if hasattr(step_output, 'tool_input') and step_output.tool_input:
                     data["tool_input"] = step_output.tool_input
                if hasattr(step_output, 'tool_output') and step_output.tool_output:
                     output = str(step_output.tool_output)
                     if len(output) > 500:
                         output = output[:500] + "... [Truncated for log]"
                     data["tool_output"] = output
                
                queue.put(data)

            except Exception as e:
                logger.error(f"Error processing step callback: {e}")
                
        def task_callback(task_output):
            """Callback for task completion/start events."""
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")
                
            try:
                # 1. Emit phase completion event
                task_desc = getattr(task_output, 'description', 'Unknown Task')
                agent_role = getattr(task_output, 'agent', 'Unknown Agent')
                
                phase_map = {
                    '文档处理专家': 'phase_1',
                    '内容分析师': 'phase_2', # Covers both A and B
                    '交叉验证员': 'phase_3',
                    '审计员': 'phase_4',
                    '审查员': 'phase_5'
                }
                
                phase_id = phase_map.get(agent_role, 'unknown_phase')
                
                # Emit task_completed for progress bar
                queue.put({
                    "type": "task_completed",
                    "data": {
                        "phase_id": phase_id,
                        "agent": agent_role,
                        "description": task_desc,
                        "timestamp": 0
                    }
                })
                
            except Exception as e:
                logger.error(f"Error in task callback: {e}")

        # Run the crew
        crew = FigureTableCrew(file_path)
        result = crew.run(step_callback=step_callback, task_callback=task_callback)
        
        # Send final result
        # Frontend expects 'result' type with markdown in 'data'
        queue.put({
            "type": "result", 
            "data": str(result)
        })
        logger.info(f"Session {session_id} completed successfully")

    except Exception as e:
        if stop_event.is_set() or str(e) == "Audit stopped by user.":
             logger.info(f"Session {session_id} stopped by user.")
             queue.put({
                "type": "stop",
                "message": "Audit stopped by user."
            })
        else:
            logger.error(f"Error in background task for session {session_id}: {e}")
            logger.error(traceback.format_exc())
            queue.put({
                "type": "error",
                "data": str(e)
            })
    finally:
        # Cleanup
        if session_id in session_queues:
            del session_queues[session_id]
        if session_id in session_events:
            del session_events[session_id]
            
        # Reset context vars
        if token_usage:
            try: session_usage.reset(token_usage)
            except: pass
        if token_queue:
            try: session_queue.reset(token_queue)
            except: pass

        # Signal end of stream
        queue.put(None) 

@router.post("/audit/figure-table")
async def start_audit(file: UploadFile = File(...)):
    """
    Starts the audit process and returns a session ID for streaming updates.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    session_id = str(uuid.uuid4())
    upload_dir = os.path.join(os.getcwd(), "doc_audit_agent", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    # Use a safe filename (session_id.pdf) to avoid issues with spaces or special characters in the original filename
    file_path = os.path.join(upload_dir, f"{session_id}.pdf")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"File uploaded: {file_path}")
        
        # Create a queue for this session
        queue = Queue()
        session_queues[session_id] = queue
        
        # Create a stop event for this session
        stop_event = Event()
        session_events[session_id] = stop_event
        
        # Start background thread
        thread = Thread(target=run_crew_in_background, args=(session_id, file_path, queue, stop_event))
        thread.daemon = True
        thread.start()
        
        return {
            "session_id": session_id,
            "filename": file.filename,
            "message": "Audit started. Connect to /audit/stream/{session_id} for updates."
        }
        
    except Exception as e:
        logger.error(f"Error starting audit: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/audit/stop/{session_id}")
async def stop_audit(session_id: str):
    """
    Stops the audit process for the given session ID.
    """
    if session_id in session_events:
        session_events[session_id].set()
        logger.info(f"Stop signal sent for session {session_id}")
        return {"message": "Audit stop signal sent."}
    else:
        # If not found, it might have already finished or doesn't exist
        # We return success anyway to be idempotent from UI perspective if it's just a cleanup
        return {"message": "Session not active or already finished."}

@router.get("/audit/stream/{session_id}")
async def stream_audit(session_id: str):
    """
    Streams updates for the given session ID using Server-Sent Events (SSE).
    """
    if session_id not in session_queues:
        # If the queue is gone, the session might have finished or been cleaned up.
        # But we can't reconnect to a finished session unless we persist results.
        # For now, return 404.
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
                    data = queue.get_nowait()
                    
                    if data is None: # Signal for end of stream
                        break
                    
                    # Reset activity timer on new data
                    last_activity = time.time()
                    
                    # Format as SSE
                    yield f"data: {json.dumps(data)}\n\n"
                    
                    # Check if this is a terminal event
                    if data.get("type") in ["result", "error", "stop"]:
                        # We still continue to yield until None is received, 
                        # but usually backend sends None right after.
                        pass
                        
                except Empty:
                    # No data available, check keep-alive
                    await asyncio.sleep(0.1)
                    
                    if time.time() - last_activity > 15:
                        # Send comment as keep-alive
                        yield ": keep-alive\n\n"
                        last_activity = time.time()
                        
            except Exception as e:
                logger.error(f"Error in event generator: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break
        
        # Cleanup
        if session_id in session_queues:
            del session_queues[session_id]
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import shutil
import os
import uuid
import logging
import json
import asyncio
import time
from queue import Empty

from app.core.runner import AgentRunner
from app.core.llm import LLMFactory
import litellm

# 配置日志记录器
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/agents", summary="获取智能体列表", description="获取系统中所有可用的智能体及其描述。")
async def list_agents():
    """列出所有可用的智能体。"""
    return AgentRunner.list_agents()

@router.post("/run/{agent_id}", summary="运行智能体", description="上传PDF文件并启动指定的智能体任务。返回会话ID用于追踪进度。", response_description="包含会话ID、状态消息和文件路径的JSON对象。")
async def run_agent(agent_id: str, file: UploadFile = File(...)):
    """
    上传文件并启动指定的智能体。
    返回一个 session_id 用于订阅 SSE 更新。
    """
    # 验证文件类型
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    # 生成会话 ID
    session_id = str(uuid.uuid4())
    
    # 创建上传目录
    upload_dir = os.path.join("uploads")
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    # 保存文件
    # 文件名前缀加上 session_id 以避免冲突
    original_filename = os.path.basename(file.filename)
    sanitized_filename = original_filename.replace(" ", "_")
    safe_filename = f"{session_id}_{sanitized_filename}"
    file_path = os.path.join(upload_dir, safe_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 通过 AgentRunner 启动智能体
    # 这将处理后台线程、历史记录和 LLM 回调上下文设置
    AgentRunner.start_agent(
        agent_id=agent_id, 
        inputs={"file_path": os.path.abspath(file_path)}, 
        session_id=session_id, 
        original_filename=original_filename
    )
    
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
    停止正在运行的会话。
    """
    if AgentRunner.stop_session(session_id):
        return {"message": "Stop signal sent"}
    else:
        raise HTTPException(status_code=404, detail="Session not found or not running")

@router.get("/stream/{session_id}", summary="监听任务进度 (SSE)", description="通过 Server-Sent Events (SSE) 实时获取任务的执行日志和结果。")
async def stream_audit(session_id: str):
    """
    使用 Server-Sent Events (SSE) 流式传输指定会话 ID 的更新。
    """
    queue = AgentRunner.get_queue(session_id)
    
    if not queue:
        # 如果在活动队列中找不到会话，检查历史记录？
        # 如果是过去的会话，我们不能通过此端点流式传输（这是用于实时更新的）。
        # 用户应使用 /history/{session_id} 获取过去的日志。
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    async def event_generator():
        # 发送初始连接消息
        yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        
        last_activity = time.time()
        
        while True:
            try:
                # 使用非阻塞获取检查新数据
                try:
                    # 使用 get_nowait 避免阻塞事件循环
                    data = queue.get_nowait()
                    
                    if data is None: # 结束流的信号
                        break
                    
                    # 收到新数据时重置活动计时器
                    last_activity = time.time()
                    
                    # 格式化为 SSE
                    yield f"data: {json.dumps(data)}\n\n"
                    
                    # 检查是否为终止事件
                    if isinstance(data, dict) and data.get("type") in ["result", "error", "stop"]:
                        # 我们仍然继续 yield 直到收到 None，
                        # 但通常后端会在之后立即发送 None。
                        pass
                        
                except Empty:
                    # 没有可用数据，让出控制权给事件循环
                    await asyncio.sleep(0.1)
                    
                    # 每 15 秒发送一次保持连接信号
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
        
        # 清理由后台任务处理，不在这里处理
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/tasks/active", summary="获取当前活动任务", description="获取所有正在运行中的智能体任务列表。")
async def list_active_tasks():
    """列出所有状态为 running 的当前任务。"""
    sessions = AgentRunner.get_history_manager().list_sessions()
    active_sessions = [s for s in sessions if s.get("status") == "running"]
    return active_sessions

@router.get("/task/progress/{session_id}", summary="获取任务当前进度", description="非流式接口，返回指定会话的当前状态、已完成的阶段以及最新的一条日志。")
async def get_task_progress(session_id: str):
    """获取指定任务的最新进度信息，适合前端轮询。"""
    session = AgentRunner.get_history_manager().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    events = session.get("events", [])
    
    # 提取完成的阶段和最新日志
    completed_tasks = []
    latest_step = None
    
    for item in events:
        event = item.get("event", {})
        e_type = event.get("type")
        
        if e_type == "task_completed":
            data = event.get("data", {})
            completed_tasks.append({
                "phase_id": data.get("phase_id"),
                "agent": data.get("agent"),
                "description": data.get("description")
            })
        elif e_type == "step":
            latest_step = event.get("content")
            
    return {
        "session_id": session_id,
        "status": session.get("status"),
        "start_time": session.get("start_time"),
        "completed_tasks_count": len(completed_tasks),
        "completed_tasks": completed_tasks,
        "latest_step": latest_step,
        "result": session.get("result") if session.get("status") == "completed" else None
    }

@router.get("/history", summary="获取历史记录", description="获取所有已结束（非运行中）的历史任务会话列表（按时间倒序）。")
async def list_history():
    """列出所有已结束的历史会话（完成、失败或停止）。"""
    sessions = AgentRunner.get_history_manager().list_sessions()
    # 过滤掉正在运行的任务，只返回已经结束的任务
    history_sessions = [s for s in sessions if s.get("status") != "running"]
    return history_sessions

@router.get("/history/{session_id}", summary="获取会话详情", description="获取指定会话的详细信息，包括完整的日志记录。")
async def get_history_session(session_id: str):
    """获取特定会话的详细信息和日志。"""
    session = AgentRunner.get_history_manager().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

async def extract_conclusion_from_markdown(markdown_text: str) -> bool:
    """使用 LLM 从 Markdown 结果中提取是否通过的结论"""
    if not markdown_text:
        return False
    try:
        model_name = os.getenv("MODEL_NAME", "qwen3.5-flash")
        if not model_name.startswith("openai/"):
            model_name = f"openai/{model_name}"
            
        api_key = os.getenv("ALIYUN_API_KEY")
        base_url = os.getenv("ALIYUN_API_BASE")
        
        response = await litellm.acompletion(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            messages=[
                {"role": "system", "content": "你是一个审计结果提取助手。请阅读以下审计报告，并判断该文档是否符合要求（通过审计）。如果符合/通过/无错误，请仅回复 'true'；如果不符合/不通过/存在错误/存在不一致，请仅回复 'false'。除了 'true' 或 'false' 不要输出任何其他内容。"},
                {"role": "user", "content": markdown_text}
            ],
            temperature=0.1
        )
        content = response.choices[0].message.content.strip().lower()
        return "true" in content
    except Exception as e:
        logger.error(f"Failed to extract conclusion via LLM: {e}")
        # 降级：简单的关键字匹配
        return "不通过" not in markdown_text and "不一致" not in markdown_text and "错误" not in markdown_text

@router.get("/result/{session_id}", summary="获取结构化结果", description="获取指定会话的JSON格式的审核结果，包含结论(true/false)和完整的Markdown报告。")
async def get_structured_result(session_id: str):
    """
    获取结构化的最终结果。
    返回 JSON 格式封装：
    {
      "conclusion": true/false,
      "result": "markdown content..."
    }
    """
    session = AgentRunner.get_history_manager().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    status = session.get("status")
    if status != "completed":
        return {
            "conclusion": False,
            "result": "任务尚未完成或已失败。",
            "status": status
        }
        
    result_md = session.get("result", "")
    conclusion = await extract_conclusion_from_markdown(result_md)
    
    return {
        "conclusion": conclusion,
        "result": result_md,
        "status": status
    }

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
import shutil
import os
import uuid
import logging
import json
import asyncio
import time
import re
from queue import Empty

from app.core.runner import AgentRunner
from app.core.agent_manager import AgentManager
import litellm

# 配置日志记录器
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

router = APIRouter()


def _sanitize_filename(filename: str) -> str:
    original_filename = os.path.basename(filename or "uploaded.pdf")
    sanitized_filename = original_filename.replace(" ", "_")
    return sanitized_filename or "uploaded.pdf"


def _normalize_uploaded_files(file: Optional[UploadFile], files: Optional[List[UploadFile]]) -> List[UploadFile]:
    normalized_files: List[UploadFile] = []

    if file is not None:
        normalized_files.append(file)

    if files:
        normalized_files.extend(files)

    return [
        uploaded_file
        for uploaded_file in normalized_files
        if getattr(uploaded_file, "filename", None) and getattr(uploaded_file, "file", None)
    ]

@router.get("/agents", summary="获取智能体列表", description="获取系统中所有可用的智能体及其描述。")
async def list_agents():
    """列出所有可用的智能体。"""
    return AgentRunner.list_agents()

@router.post(
    "/run/{agent_id}",
    summary="运行智能体",
    description="上传一个或多个 PDF 文件并启动指定的智能体任务。返回会话ID用于追踪进度。",
    response_description="包含会话ID、状态消息和文件信息的JSON对象。",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "format": "binary",
                                },
                                "description": "选择一个或多个 PDF 文件上传",
                            }
                        },
                    }
                }
            },
        }
    },
)
async def run_agent(
    agent_id: str,
    request: Request,
):
    """
    上传文件并启动指定的智能体。
    返回一个 session_id 用于订阅 SSE 更新。
    """
    manager = AgentManager()
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    form_data = await request.form()
    legacy_file = form_data.get("file")
    uploaded_files = _normalize_uploaded_files(legacy_file, form_data.getlist("files"))
    if not uploaded_files:
        raise HTTPException(status_code=400, detail="At least one PDF file is required.")

    file_count = len(uploaded_files)
    if file_count < agent.min_file_count:
        raise HTTPException(status_code=400, detail=f"{agent.display_name} 至少需要上传 {agent.min_file_count} 个文件。")

    if agent.max_file_count is not None and file_count > agent.max_file_count:
        raise HTTPException(status_code=400, detail=f"{agent.display_name} 最多只支持 {agent.max_file_count} 个文件，当前上传了 {file_count} 个。")

    for uploaded_file in uploaded_files:
        if not uploaded_file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    session_id = str(uuid.uuid4())
    upload_dir = os.path.abspath(os.path.join("uploads", session_id))
    os.makedirs(upload_dir, exist_ok=True)

    saved_files = []
    used_names = set()
    for index, uploaded_file in enumerate(uploaded_files, start=1):
        original_filename = os.path.basename(uploaded_file.filename)
        safe_name = _sanitize_filename(original_filename)

        if safe_name in used_names:
            name_root, extension = os.path.splitext(safe_name)
            safe_name = f"{name_root}_{index}{extension}"

        used_names.add(safe_name)
        file_path = os.path.abspath(os.path.join(upload_dir, f"{index:02d}_{safe_name}"))

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(uploaded_file.file, buffer)

        saved_files.append({
            "name": original_filename,
            "path": file_path,
            "content_type": uploaded_file.content_type,
        })

    primary_file = saved_files[0]
    inputs = {
        "files": saved_files,
        "file_paths": [item["path"] for item in saved_files],
        "file_names": [item["name"] for item in saved_files],
        "file_count": len(saved_files),
        "primary_file": primary_file,
        "primary_file_path": primary_file["path"],
        "file_path": primary_file["path"],
        "file_name": primary_file["name"],
        "content_type": primary_file.get("content_type"),
    }

    AgentRunner.start_agent(
        agent_id=agent_id, 
        inputs=inputs,
        session_id=session_id, 
        files=saved_files
    )
    
    return {
        "session_id": session_id, 
        "message": "Agent started successfully", 
        "file_path": primary_file["path"],
        "file_paths": inputs["file_paths"],
        "file_name": primary_file["name"],
        "file_names": inputs["file_names"],
        "file_count": len(saved_files),
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


def _normalize_report_field_value(value: str) -> str:
    normalized_value = re.sub(r"\*\*|__|`", "", value or "")
    normalized_value = normalized_value.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    return normalized_value.strip()


def _extract_report_field(markdown_text: str, field_name: str) -> Optional[str]:
    if not markdown_text:
        return None

    pattern = rf"^\|\s*{re.escape(field_name)}\s*\|\s*(.*?)\s*\|$"
    match = re.search(pattern, markdown_text, flags=re.MULTILINE)
    if not match:
        return None

    value = _normalize_report_field_value(match.group(1))
    return value or None


def _extract_explicit_conclusion(markdown_text: str) -> Optional[bool]:
    explicit_result = _extract_report_field(markdown_text, "审计结果")
    if not explicit_result:
        explicit_result = _extract_report_field(markdown_text, "检查项最终结论")

    if not explicit_result:
        return None

    if any(keyword in explicit_result for keyword in ("不通过", "不符合", "失败", "存疑")):
        return False
    if "通过" in explicit_result:
        return True
    return None


async def extract_conclusion_from_markdown(markdown_text: str) -> bool:
    """使用 LLM 从 Markdown 结果中提取是否通过的结论"""
    if not markdown_text:
        return False

    explicit_conclusion = _extract_explicit_conclusion(markdown_text)
    if explicit_conclusion is not None:
        return explicit_conclusion

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
                {"role": "system", "content": "你是一个审计结果提取助手。请优先读取报告综述中的“审计结果”或“检查项最终结论”字段，并仅根据该字段判断文档是否通过审计。`AB轮交叉验证状态` 只表示复核过程是否出现分歧，不等同于文档错误，不能仅因该字段出现“存在分歧”就判定 false。如果审计结果为通过/符合，请仅回复 'true'；如果审计结果为不通过/不符合/存疑，请仅回复 'false'。除了 'true' 或 'false' 不要输出任何其他内容。"},
                {"role": "user", "content": markdown_text}
            ],
            temperature=0.1
        )
        content = response.choices[0].message.content.strip().lower()
        return "true" in content
    except Exception as e:
        logger.error(f"Failed to extract conclusion via LLM: {e}")
        fallback_conclusion = _extract_explicit_conclusion(markdown_text)
        if fallback_conclusion is not None:
            return fallback_conclusion
        return "不通过" not in markdown_text and "错误" not in markdown_text

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
    ab_consistency_status = _extract_report_field(result_md, "AB轮交叉验证状态")
    audit_result = _extract_report_field(result_md, "审计结果")
    finding_conclusion = _extract_report_field(result_md, "检查项最终结论")
    
    return {
        "conclusion": conclusion,
        "audit_result": audit_result,
        "finding_conclusion": finding_conclusion,
        "ab_consistency_status": ab_consistency_status,
        "result": result_md,
        "status": status
    }

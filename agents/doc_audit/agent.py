from crewai import Crew, Process, LLM
from agents.doc_audit.roles import FigureTableRoles
from agents.doc_audit.tasks import FigureTableTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
import os
from typing import Dict, Any
from queue import Queue
from threading import Event
from dotenv import load_dotenv

load_dotenv()

class DocAuditAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "doc_audit"

    @property
    def display_name(self) -> str:
        return "文档图表一致性审计"

    @property
    def description(self) -> str:
        return "自动检查文档中的图表目录与正文内容是否一致。"

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        pdf_path = self.get_primary_input_file(inputs).get("path")

        # Initialize Crew components
        roles = FigureTableRoles()
        tasks = FigureTableTasks()
        
        # Configure LLM
        # 使用工厂模式创建 LLM，支持 task/agent 级别的模型调度
        llm = LLMFactory.get_aliyun_llm()

        # 示例：如果某个特定任务需要使用 Ollama 的本地模型
        # ollama_llm = LLMFactory.get_ollama_llm(model_name="llama3")
        
        # 示例：如果想给特定 agent 分配不同的 LLM，可以在创建时传入不同的 llm 实例
        # analyzer_b = agents.content_analyzer_agent(ollama_llm, step_callback)

        # Callbacks (adapted from original routes.py logic)
        def step_callback(step_output):
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")
            
            try:
                # Note: Token usage tracking logic should be handled by a global callback or passed context
                # For now, we simplify and focus on step output
                data = {
                    "type": "step",
                    "content": str(step_output)
                }
                
                # Phase mapping
                phase_map = {
                    '文档处理专家': 'phase_1',
                    '内容分析师': 'phase_2',
                    '交叉验证员': 'phase_3',
                    '审计员': 'phase_4',
                    '审查员': 'phase_5'
                }

                if hasattr(step_output, 'agent') and step_output.agent:
                    if hasattr(step_output.agent, 'role'):
                        data["agent"] = step_output.agent.role
                        data["phase_id"] = phase_map.get(step_output.agent.role, 'unknown_phase')
                    else:
                        data["agent"] = str(step_output.agent)
                        data["phase_id"] = phase_map.get(str(step_output.agent), 'unknown_phase')
                
                thought = ""
                if hasattr(step_output, 'thought') and step_output.thought:
                     thought = step_output.thought
                
                # Enhanced error handling for "Failed to parse"
                if "Failed to parse" in thought or "Could not parse" in thought:
                    raw_output = None
                    # Try to find raw output in various attributes
                    if hasattr(step_output, 'text') and step_output.text:
                        raw_output = step_output.text
                    elif hasattr(step_output, 'result') and step_output.result:
                        raw_output = step_output.result
                    
                    if raw_output:
                        thought += f"\n\n[System Info] 原始 LLM 输出:\n{raw_output}"

                data["thought"] = thought

                if hasattr(step_output, 'tool') and step_output.tool:
                     data["tool"] = step_output.tool
                if hasattr(step_output, 'tool_input') and step_output.tool_input:
                     data["tool_input"] = step_output.tool_input
                if hasattr(step_output, 'tool_output') and step_output.tool_output:
                     output = str(step_output.tool_output)
                     if len(output) > 500:
                         output = output[:500] + "... [Truncated for log]"
                     data["tool_output"] = output
                
                # Push step update immediately to queue
                queue.put(data)
            except Exception as e:
                # Log error (assuming logger is set up, or just print)
                print(f"Error processing step callback: {e}")

        def task_callback(task_output):
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")
                
            try:
                task_desc = getattr(task_output, 'description', 'Unknown Task')
                agent_role = getattr(task_output, 'agent', 'Unknown Agent')
                
                # Phase mapping
                phase_map = {
                    '文档处理专家': 'phase_1',
                    '内容分析师': 'phase_2',
                    '交叉验证员': 'phase_3',
                    '审计员': 'phase_4',
                    '审查员': 'phase_5'
                }
                phase_id = phase_map.get(agent_role, 'unknown_phase')
                
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
                print(f"Error in task callback: {e}")

        # Create Agents 通过llm来指定模型
        processor = roles.document_processor_agent(llm, step_callback)
        analyzer_a = roles.content_analyzer_agent(llm, step_callback)
        analyzer_b = roles.content_analyzer_agent(llm, step_callback)
        verifier = roles.verification_agent(llm, step_callback)
        auditor = roles.auditor_agent(llm, step_callback)
        reviewer = roles.reviewer_agent(llm, step_callback)
        
        # Create Tasks
        task1 = tasks.process_document_task(processor, pdf_path)
        task2_a = tasks.analyze_content_task(analyzer_a, task1)
        task2_b = tasks.analyze_content_task_b(analyzer_b, task1)
        task3 = tasks.verify_analysis_task(verifier, task2_a, task2_b, task1)
        task4 = tasks.audit_content_task(auditor, task3)
        task5 = tasks.review_and_report_task(reviewer, task4)

        # Create Crew
        crew = Crew(
            agents=[processor, analyzer_a, analyzer_b, verifier, auditor, reviewer],
            tasks=[task1, task2_a, task2_b, task3, task4, task5],
            process=Process.sequential,
            verbose=True,
            memory=False,
            step_callback=step_callback,
            task_callback=task_callback
        )

        result = crew.kickoff()
        return result

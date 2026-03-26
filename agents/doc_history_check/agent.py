from crewai import Crew, Process
from agents.doc_history_check.roles import DocHistoryRoles
from agents.doc_history_check.tasks import DocHistoryTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
import os
from typing import Dict, Any, List
from queue import Queue
from threading import Event

class DocHistoryCheckAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "doc_history_check"

    @property
    def display_name(self) -> str:
        return "历史版本完整性审查"

    @property
    def description(self) -> str:
        return "文档版本记录是否正确列出历史版本及其作者，是否正确列出历史版本的变更单据信息？"

    @property
    def min_file_count(self) -> int:
        return 1

    @property
    def max_file_count(self) -> int:
        return 1

    @property
    def accepts_multiple_files(self) -> bool:
        return False

    @property
    def phase_definitions(self) -> List[Dict[str, str]]:
        return [
            {"id": "phase_1", "label": "文档解析"},
            {"id": "phase_2", "label": "内容提取"},
            {"id": "phase_3", "label": "交叉验证"},
            {"id": "phase_4", "label": "结论生成"},
        ]

    @property
    def phase_task_requirements(self) -> Dict[str, int]:
        return {
            "phase_1": 1,
            "phase_2": 2, # AB轮次
            "phase_3": 1,
            "phase_4": 1,
        }

    @property
    def role_phase_map(self) -> Dict[str, str]:
        return {
            '文档处理专家': 'phase_1',
            '内容分析师': 'phase_2',
            '交叉验证员': 'phase_3',
            '审查员': 'phase_4'
        }

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        primary_file = self.get_primary_input_file(inputs)
        if not primary_file:
            queue.put({
                "type": "error",
                "error": "未提供有效的文件输入或文件列表为空"
            })
            return {"conclusion": False, "reason": "文件为空"}
            
        pdf_path = primary_file.get("path")
        if not pdf_path or not os.path.exists(pdf_path):
            queue.put({
                "type": "error",
                "error": "无法读取提供的 PDF 文件"
            })
            return {"conclusion": False, "reason": "文件不存在"}

        roles = DocHistoryRoles()
        tasks = DocHistoryTasks()
        
        # 使用工厂模式创建 LLM
        llm = LLMFactory.get_aliyun_llm()

        def step_callback(step_output):
            if stop_event.is_set():
                raise RuntimeError("Task stopped by user.")
            
            try:
                data = {
                    "type": "step",
                    "content": str(step_output)
                }
                
                phase_map = self.role_phase_map

                if hasattr(step_output, 'agent') and step_output.agent:
                    role_name = getattr(step_output.agent, 'role', str(step_output.agent))
                    data["agent"] = role_name
                    data["phase_id"] = phase_map.get(role_name, 'unknown_phase')
                
                thought = getattr(step_output, 'thought', "")
                if "Failed to parse" in thought or "Could not parse" in thought:
                    raw_output = getattr(step_output, 'text', getattr(step_output, 'result', None))
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
                     
                # Add llm_io indicator if it has thought and agent
                if data.get("thought") or data.get("tool"):
                    data["is_llm_io"] = True
                
                queue.put(data)
            except Exception as e:
                print(f"Error processing step callback: {e}")

        def task_callback(task_output):
            if stop_event.is_set():
                raise RuntimeError("Task stopped by user.")
                
            try:
                task_desc = getattr(task_output, 'description', 'Unknown Task')
                agent_role = getattr(task_output, 'agent', 'Unknown Agent')
                
                phase_id = self.role_phase_map.get(agent_role, 'unknown_phase')
                
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

        try:
            processor = roles.document_processor_agent(llm, step_callback)
            analyzer_a = roles.content_analyzer_agent(llm, step_callback)
            analyzer_b = roles.content_analyzer_agent(llm, step_callback)
            verifier = roles.verification_agent(llm, step_callback)
            reviewer = roles.reviewer_agent(llm, step_callback)
            
            task1 = tasks.process_document_task(processor, pdf_path)
            task2_a = tasks.analyze_content_task(analyzer_a, task1)
            task2_b = tasks.analyze_content_task_b(analyzer_b, task1)
            task3 = tasks.verify_analysis_task(verifier, task2_a, task2_b, task1)
            task4 = tasks.review_and_report_task(reviewer, task3)

            crew = Crew(
                agents=[processor, analyzer_a, analyzer_b, verifier, reviewer],
                tasks=[task1, task2_a, task2_b, task3, task4],
                process=Process.sequential,
                verbose=True,
                memory=False,
                step_callback=step_callback,
                task_callback=task_callback
            )

            result_str = crew.kickoff()
            
            # Send final result to queue
            queue.put({
                "type": "result",
                "result": str(result_str)
            })
            
            return result_str
            
        except RuntimeError as e:
            if "stopped by user" in str(e).lower():
                queue.put({
                    "type": "error",
                    "error": "任务被用户停止"
                })
                return {"conclusion": False, "reason": "已中止"}
            raise e
        except Exception as e:
            queue.put({
                "type": "error",
                "error": f"智能体执行异常: {str(e)}"
            })
            return {"conclusion": False, "reason": "执行异常"}

from crewai import Crew, Process
from .roles import TOCStructureRoles
from .tasks import TOCStructureTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
from typing import Dict, Any, List
from queue import Queue
from threading import Event
from dotenv import load_dotenv
import os
import re

load_dotenv()

class TOCStructureCheckAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "doc_toc_structure_check"

    @property
    def display_name(self) -> str:
        return "目录结构一致性审查"

    @property
    def description(self) -> str:
        return "检查文档目次是否与正文目录结构一致，采用A轮、B轮交叉验证机制确保结果准确。"

    @property
    def category_folder(self) -> str:
        return "4_PSAC"

    @property
    def category_name(self) -> str:
        return "软件合格审定计划"

    @property
    def checklist_items(self) -> List[Dict[str, str]]:
        return [
            {
                "item_no": "4",
                "content": "文档是否有目次？",
            },
            {
                "item_no": "5",
                "content": "目次是否与正文中目录结构一致？",
            },
        ]

    @property
    def min_file_count(self) -> int:
        return 1

    @property
    def max_file_count(self) -> int:
        return 1

    @property
    def phase_definitions(self) -> List[Dict[str, str]]:
        return [
            {"id": "phase_1", "label": "文档解析"},
            {"id": "phase_2", "label": "A轮目录检查"},
            {"id": "phase_3", "label": "B轮目录检查"},
            {"id": "phase_4", "label": "交叉验证与报告生成"},
        ]

    @property
    def phase_task_requirements(self) -> Dict[str, int]:
        return {
            "phase_1": 1,
            "phase_2": 1,
            "phase_3": 1,
            "phase_4": 1,
        }

    @property
    def role_phase_map(self) -> Dict[str, str]:
        return {
            '文档解析专家': 'phase_1',
            'A轮目录检查专家': 'phase_2',
            'B轮目录检查专家': 'phase_3',
            '交叉验证专家': 'phase_4'
        }

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        file_info = self.get_primary_input_file(inputs)
        pdf_path = file_info.get("path")

        roles = TOCStructureRoles()
        tasks = TOCStructureTasks()
        
        llm = LLMFactory.get_aliyun_llm()

        def step_callback(step_output):
            if stop_event.is_set():
                raise RuntimeError("审查任务已被用户停止。")
            
            try:
                data = {
                    "type": "step",
                    "content": str(step_output)
                }
                
                phase_map = self.role_phase_map

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
                
                if "Failed to parse" in thought or "Could not parse" in thought:
                    raw_output = None
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
                         output = output[:500] + "... [已截断]"
                     data["tool_output"] = output
                
                queue.put(data)
            except Exception as e:
                print(f"Error processing step callback: {e}")

        def task_callback(task_output):
            if stop_event.is_set():
                raise RuntimeError("审查任务已被用户停止。")
                
            try:
                task_desc = getattr(task_output, 'description', 'Unknown Task')
                agent_role = getattr(task_output, 'agent', 'Unknown Agent')
                
                phase_map = self.role_phase_map
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

        parser = roles.document_parser_agent(llm, step_callback)
        checker_a = roles.toc_checker_a_agent(llm, step_callback)
        checker_b = roles.toc_checker_b_agent(llm, step_callback)
        validator = roles.cross_validator_agent(llm, step_callback)
        
        task1 = tasks.parse_document_task(parser, pdf_path)
        task2 = tasks.toc_check_task_a(checker_a, task1)
        task3 = tasks.toc_check_task_b(checker_b, task1)
        task4 = tasks.cross_validate_task(validator, task2, task3)

        crew = Crew(
            agents=[parser, checker_a, checker_b, validator],
            tasks=[task1, task2, task3, task4],
            process=Process.sequential,
            verbose=True,
            memory=False,
            step_callback=step_callback,
            task_callback=task_callback
        )

        result = crew.kickoff()
        
        result_str = str(result)
        
        markdown_report = ""
        if "目录结构一致性审查报告" in result_str:
            match = re.search(r'# 目录结构一致性审查报告.*', result_str, re.DOTALL)
            if match:
                markdown_report = match.group(0)
        
        if not markdown_report:
            for task in [task4, task3, task2]:
                if hasattr(task, 'output') and task.output:
                    task_output = str(task.output)
                    if "目录结构一致性审查报告" in task_output:
                        match = re.search(r'# 目录结构一致性审查报告.*', task_output, re.DOTALL)
                        if match:
                            markdown_report = match.group(0)
                            break
        
        conclusion = "不通过"
        if "**通过**" in result_str or "判定结果**：**通过" in result_str:
            conclusion = "通过"
        elif "缺少目录" in result_str:
            conclusion = "缺少目录"
        elif "解析异常" in result_str:
            conclusion = "解析异常"
        
        if "非附录重置" in result_str and "是" in result_str:
            conclusion = "不通过"
        if "页码重置" in result_str and "异常" in result_str:
            conclusion = "不通过"
        
        queue.put({
            "type": "result",
            "data": markdown_report
        })
        
        final_result = {
            "conclusion": conclusion,
            "markdown_report": markdown_report
        }
        
        return final_result

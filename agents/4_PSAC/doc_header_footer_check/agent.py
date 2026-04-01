from crewai import Crew, Process
from .roles import HeaderFooterRoles
from .tasks import HeaderFooterTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
import os
from typing import Dict, Any, List
from queue import Queue
from threading import Event
from dotenv import load_dotenv
import json

load_dotenv()


class DocHeaderFooterCheckAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "doc_header_footer_check"

    @property
    def display_name(self) -> str:
        return "页眉页脚完整性审查"

    @property
    def description(self) -> str:
        return "检查页眉页脚是否符合模板要求，重点核验页眉中的文件编号、文件版本，以及页脚中的版权信息和页码连续性"

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
                "item_no": "8",
                "content": "页眉是否包含文件编号和文件版本？",
            },
            {
                "item_no": "9",
                "content": "页眉中的文件编号、文件版本是否与首页一致？",
            },
            {
                "item_no": "10",
                "content": "页脚是否包含版权信息和页码，且正文页码是否连续？",
            },
        ]

    @property
    def phase_definitions(self) -> List[Dict[str, str]]:
        return [
            {"id": "phase_1", "label": "文档解析"},
            {"id": "phase_2", "label": "基准信息提取"},
            {"id": "phase_3", "label": "页眉页脚识别"},
            {"id": "phase_4", "label": "A轮核验"},
            {"id": "phase_5", "label": "B轮核验"},
            {"id": "phase_6", "label": "交叉验证"},
            {"id": "phase_7", "label": "结果生成"},
        ]

    @property
    def phase_task_requirements(self) -> Dict[str, int]:
        return {
            "phase_1": 1,
            "phase_2": 1,
            "phase_3": 1,
            "phase_4": 1,
            "phase_5": 1,
            "phase_6": 1,
            "phase_7": 1,
        }

    @property
    def role_phase_map(self) -> Dict[str, str]:
        return {
            '文档解析员': 'phase_1',
            '基准提取员': 'phase_2',
            '页眉页脚识别员': 'phase_3',
            'A轮核验员': 'phase_4',
            'B轮核验员': 'phase_5',
            '交叉验证员': 'phase_6',
            '报告生成员': 'phase_7'
        }

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        pdf_path = self.get_primary_input_file(inputs).get("path")

        roles = HeaderFooterRoles()
        tasks = HeaderFooterTasks()
        
        llm = LLMFactory.get_aliyun_llm()

        def step_callback(step_output):
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")
            
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
                         output = output[:500] + "... [Truncated for log]"
                     data["tool_output"] = output
                
                queue.put(data)
            except Exception as e:
                print(f"Error processing step callback: {e}")

        def task_callback(task_output):
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")
                
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

        parser = roles.parser_agent(llm, step_callback)
        baseline_extractor = roles.baseline_extractor_agent(llm, step_callback)
        header_footer_identifier = roles.header_footer_identifier_agent(llm, step_callback)
        a_round_checker = roles.a_round_checker_agent(llm, step_callback)
        b_round_checker = roles.b_round_checker_agent(llm, step_callback)
        cross_validator = roles.cross_validator_agent(llm, step_callback)
        report_generator = roles.report_generator_agent(llm, step_callback)
        
        task1 = tasks.parse_document_task(parser, pdf_path)
        task2 = tasks.extract_baseline_task(baseline_extractor, task1)
        task3 = tasks.identify_header_footer_task(header_footer_identifier, task1)
        task4 = tasks.a_round_check_task(a_round_checker, task2, task3)
        task5 = tasks.b_round_check_task(b_round_checker, task2, task3)
        task6 = tasks.cross_validate_task(cross_validator, task4, task5, task2, task3)
        task7 = tasks.generate_report_task(report_generator, task6)

        crew = Crew(
            agents=[parser, baseline_extractor, header_footer_identifier, 
                    a_round_checker, b_round_checker, cross_validator, report_generator],
            tasks=[task1, task2, task3, task4, task5, task6, task7],
            process=Process.sequential,
            verbose=True,
            memory=False,
            step_callback=step_callback,
            task_callback=task_callback
        )

        result = crew.kickoff()
        return result

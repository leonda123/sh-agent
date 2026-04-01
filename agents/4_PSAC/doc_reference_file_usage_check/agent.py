from crewai import Crew, Process
from .roles import ReferenceFileRoles
from .tasks import ReferenceFileTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
import os
from typing import Dict, Any, List
from queue import Queue
from threading import Event
from dotenv import load_dotenv
import re

load_dotenv()

class ReferenceFileUsageCheckAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "doc_reference_file_usage_check"

    @property
    def display_name(self) -> str:
        return "文档引用文件检查"

    @property
    def description(self) -> str:
        return "检查文档是否存在\"引用文件\"或\"参考文件\"章节，并核验其中列出的文件是否在正文中均有引用"

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
                "item_no": "10",
                "content": "是否存在\"引用文件\"或\"参考文件\"章节？",
            },
            {
                "item_no": "11",
                "content": "章节及其子章节中的各个文件是否可识别？",
            },
            {
                "item_no": "12",
                "content": "识别出的各个文件是否在正文中至少出现两次？",
            },
        ]

    @property
    def phase_definitions(self) -> List[Dict[str, str]]:
        return [
            {"id": "phase_1", "label": "文档解析"},
            {"id": "phase_2", "label": "引用文件提取"},
            {"id": "phase_3", "label": "A轮核验"},
            {"id": "phase_4", "label": "B轮核验"},
            {"id": "phase_5", "label": "交叉验证"},
            {"id": "phase_6", "label": "报告生成"},
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
        }

    @property
    def role_phase_map(self) -> Dict[str, str]:
        return {
            '文档解析员': 'phase_1',
            '引用文件提取员': 'phase_2',
            'A轮核验员': 'phase_3',
            'B轮核验员': 'phase_4',
            '交叉验证员': 'phase_5',
            '报告生成员': 'phase_6'
        }

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        file_info = self.get_primary_input_file(inputs)
        pdf_path = file_info.get("path")
        file_name = file_info.get("name", os.path.basename(pdf_path))
        
        roles = ReferenceFileRoles()
        tasks = ReferenceFileTasks()
        
        llm = LLMFactory.get_aliyun_llm()

        def step_callback(step_output):
            if stop_event.is_set():
                raise RuntimeError("检查任务已被用户停止。")
            
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
                raise RuntimeError("检查任务已被用户停止。")
                
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
        extractor = roles.reference_file_extractor_agent(llm, step_callback)
        checker_a = roles.a_round_checker_agent(llm, step_callback)
        checker_b = roles.b_round_checker_agent(llm, step_callback)
        validator = roles.cross_validator_agent(llm, step_callback)
        reporter = roles.report_generator_agent(llm, step_callback)
        
        task1 = tasks.parse_document_task(parser, pdf_path)
        task2 = tasks.extract_reference_files_task(extractor, task1)
        task3 = tasks.a_round_check_task(checker_a, task2, task1)
        task4 = tasks.b_round_check_task(checker_b, task2, task1)
        task5 = tasks.cross_validation_task(validator, task3, task4, task2, task1)
        task6 = tasks.generate_report_task(reporter, task5, task2, file_name)

        crew = Crew(
            agents=[parser, extractor, checker_a, checker_b, validator, reporter],
            tasks=[task1, task2, task3, task4, task5, task6],
            process=Process.sequential,
            verbose=True,
            memory=False,
            step_callback=step_callback,
            task_callback=task_callback
        )

        result = crew.kickoff()
        
        result_str = str(result)
        
        markdown_report = ""
        if "引用文件使用情况检查报告" in result_str:
            match = re.search(r'# 引用文件使用情况检查报告.*', result_str, re.DOTALL)
            if match:
                markdown_report = match.group(0)
        
        if not markdown_report:
            for task in [task6, task5, task4, task3, task2]:
                if hasattr(task, 'output') and task.output:
                    task_output = str(task.output)
                    if "引用文件使用情况检查报告" in task_output:
                        match = re.search(r'# 引用文件使用情况检查报告.*', task_output, re.DOTALL)
                        if match:
                            markdown_report = match.group(0)
                            break
        
        conclusion = "不通过"
        if "**通过**" in result_str or "审查结果**：**通过" in result_str:
            conclusion = "通过"
        elif "未找到" in result_str and "引用文件" in result_str:
            conclusion = "缺少引用文件章节"
        elif "解析异常" in result_str or "解析失败" in result_str:
            conclusion = "解析异常"
        
        if "异常文件" in result_str and "未发现异常文件" not in result_str:
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

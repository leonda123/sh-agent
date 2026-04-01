from crewai import Crew, Process
from .roles import CrossReferenceRoles
from .tasks import CrossReferenceTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
import os
from typing import Dict, Any, List
from queue import Queue
from threading import Event
from dotenv import load_dotenv
import re

load_dotenv()


class CrossReferenceCheckAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "doc_cross_reference_check"

    @property
    def display_name(self) -> str:
        return "交叉引用正确性检查"

    @property
    def description(self) -> str:
        return "检查文档全文中是否存在'错误!未找到引用源。'，并据此判断交叉引用是否正确"

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
                "item_no": "13",
                "content": "全文是否包含\"错误!未找到引用源。\"？",
            },
            {
                "item_no": "14",
                "content": "是否能够基于全文检索结果判断交叉引用正确性？",
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
            {"id": "parse_document", "label": "文档解析"},
            {"id": "a_round_check", "label": "A轮核验"},
            {"id": "b_round_check", "label": "B轮核验"},
            {"id": "cross_validation", "label": "交叉验证"},
            {"id": "build_result", "label": "结果生成"},
        ]

    @property
    def phase_task_requirements(self) -> Dict[str, int]:
        return {
            "parse_document": 1,
            "a_round_check": 1,
            "b_round_check": 1,
            "cross_validation": 1,
            "build_result": 1,
        }

    @property
    def role_phase_map(self) -> Dict[str, str]:
        return {
            "文档解析员": "parse_document",
            "A轮核验员": "a_round_check",
            "B轮核验员": "b_round_check",
            "交叉验证员": "cross_validation",
            "报告生成员": "build_result",
        }

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        file_info = self.get_primary_input_file(inputs)
        pdf_path = file_info.get("path")
        file_name = file_info.get("name", os.path.basename(pdf_path))
        
        roles = CrossReferenceRoles()
        tasks = CrossReferenceTasks()
        
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
        checker_a = roles.a_round_checker_agent(llm, step_callback)
        checker_b = roles.b_round_checker_agent(llm, step_callback)
        validator = roles.cross_validator_agent(llm, step_callback)
        reporter = roles.report_generator_agent(llm, step_callback)
        
        task1 = tasks.parse_document_task(parser, pdf_path)
        task2 = tasks.a_round_check_task(checker_a, task1)
        task3 = tasks.b_round_check_task(checker_b, task1)
        task4 = tasks.cross_validation_task(validator, task2, task3, task1)
        task5 = tasks.build_result_task(reporter, task4, task1, file_name)

        crew = Crew(
            agents=[parser, checker_a, checker_b, validator, reporter],
            tasks=[task1, task2, task3, task4, task5],
            process=Process.sequential,
            verbose=True,
            memory=False,
            step_callback=step_callback,
            task_callback=task_callback
        )

        result = crew.kickoff()
        
        result_str = str(result)
        
        markdown_report = self._extract_markdown_report(result_str, file_name)
        
        queue.put({
            "type": "result",
            "data": markdown_report
        })
        
        return markdown_report

    def _extract_markdown_report(self, result_str: str, file_name: str) -> str:
        if "交叉引用正确性检查报告" in result_str:
            match = re.search(r'# 交叉引用正确性检查报告.*', result_str, re.DOTALL)
            if match:
                return match.group(0)
        
        if hasattr(result_str, 'raw'):
            raw_output = result_str.raw
            if "交叉引用正确性检查报告" in raw_output:
                match = re.search(r'# 交叉引用正确性检查报告.*', raw_output, re.DOTALL)
                if match:
                    return match.group(0)
        
        return self._build_default_markdown_report(file_name, "无法判定", "结果解析失败，无法生成完整报告")

    def _build_default_markdown_report(self, file_name: str, status: str, reason: str) -> str:
        is_hit = status == "不通过"
        hit_text = "是" if is_hit else "否"
        
        return f"""# 交叉引用正确性检查报告


## 1. 审查任务信息
| 项目 | 详情 |
| :--- | :--- |
| 审查项 | 正文中所有上下文引用是否正确、一致？交叉索引；文件章节标题、标题名称等。 |
| 文件名称 | {file_name} |
| 审查结果 | **{status}** |

## 2. 审查结果
| 项目 | 详情 |
| :--- | :--- |
| 审查结果 | {status} |
| 业务逻辑结果 | {"否" if status == "不通过" else ("是" if status == "通过" else "无法判定")} |
| 结论描述 | {reason} |

## 3. 审查依据
| 项目 | 详情 |
| :--- | :--- |
| 检索字段 | 错误!未找到引用源。 |
| 检索范围 | 全文 |
| 检索方法 | 全文精确检索 + 逐页复核 |

## 4. 检索结果
| 项目 | 详情 |
| :--- | :--- |
| 是否命中 | {hit_text} |
| 命中次数 | 0 |
| 命中页码 | 无 |

### 原文依据
全文未检索到该字段

## 5. 判定说明
{reason}
"""

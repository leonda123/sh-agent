from crewai import Crew, Process
from agents.doc_term.roles import TermAuditRoles
from agents.doc_term.tasks import TermAuditTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
from typing import Dict, Any
from queue import Queue
from threading import Event
from dotenv import load_dotenv

load_dotenv()

class DocTermAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "doc_term"

    @property
    def display_name(self) -> str:
        return "术语/缩略语一致性审计"

    @property
    def description(self) -> str:
        return "检查文档中是否包含术语/缩略语章节，并核实其定义与正文使用的一致性。"

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        pdf_path = inputs.get("file_path")
        if not pdf_path:
            raise ValueError("File path is required for DocTermAgent")

        # Initialize LLM
        llm = LLMFactory.get_aliyun_llm()

        # Callbacks
        def step_callback(step_output):
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")
            
            data = {
                "type": "step",
                "content": str(step_output)
            }
            
            # Phase mapping
            phase_map = {
                '文档处理专家': 'phase_1',
                '术语提取员': 'phase_2',
                '术语审计员': 'phase_3',
                '零引用复核员': 'phase_4',
                '报告生成员': 'phase_5'
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
                     output = output[:500] + "... (truncated)"
                 data["tool_output"] = output

            queue.put(data)

        def task_callback(task_output):
            if stop_event.is_set():
                raise RuntimeError("Audit stopped by user.")
            
            try:
                # In CrewAI task_output might be a string or TaskOutput object
                # We need to extract info safely
                description = "Task Completed"
                agent_role = "unknown_agent"
                
                if hasattr(task_output, 'description'):
                    description = task_output.description
                if hasattr(task_output, 'agent'):
                    temp_agent = task_output.agent
                    if hasattr(temp_agent, 'role'):
                        agent_role = temp_agent.role
                    else:
                        agent_role = str(temp_agent)
                
                # Phase mapping
                phase_map = {
                    '文档处理专家': 'phase_1',
                    '术语提取员': 'phase_2',
                    '术语审计员': 'phase_3',
                    '零引用复核员': 'phase_4',
                    '报告生成员': 'phase_5'
                }
                phase_id = phase_map.get(agent_role, 'unknown_phase')
                
                queue.put({
                    "type": "task_completed",
                    "data": {
                        "phase_id": phase_id,
                        "agent": agent_role,
                        "description": description
                    }
                })
            except Exception as e:
                # Log error but don't stop execution
                print(f"Error in task callback: {e}")

        # Initialize Roles and Tasks
        roles = TermAuditRoles(llm=llm)
        tasks = TermAuditTasks()

        # Create Agents
        processor = roles.document_processor(callback=step_callback)
        extractor = roles.term_extractor(callback=step_callback)
        auditor = roles.term_auditor(callback=step_callback)
        verifier = roles.term_verifier(callback=step_callback)
        reporter = roles.report_generator(callback=step_callback)

        # Create Tasks
        task_process = tasks.process_document_task(processor, pdf_path)
        
        # Phase 2: Double Extraction & Merge
        task_extract_a = tasks.extract_terms_task_a(extractor, task_process)
        task_extract_b = tasks.extract_terms_task_b(extractor, task_process)
        task_merge = tasks.merge_terms_task(extractor, task_extract_a, task_extract_b)
        
        # Phase 3 & 4: Audit & Verify (with Exclusion Logic)
        task_audit = tasks.audit_terms_task(auditor, task_merge, task_process)
        task_verify = tasks.verify_zero_count_task(verifier, task_audit, task_process)
        
        # Phase 5: Report
        task_report = tasks.generate_report_task(reporter, task_extract_a, task_verify) # Note: report uses merge/verify results indirectly or directly

        # Create Crew
        crew = Crew(
            agents=[processor, extractor, auditor, verifier, reporter],
            tasks=[
                task_process, 
                task_extract_a, 
                task_extract_b, 
                task_merge, 
                task_audit, 
                task_verify, 
                task_report
            ],
            process=Process.sequential,
            verbose=True,
            step_callback=step_callback,
            task_callback=task_callback
        )

        result = crew.kickoff()
        
        # Send completion event
        queue.put({
            "type": "result",
            "data": str(result)
        })
        
        return result

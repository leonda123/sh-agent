from crewai import Crew, Process, LLM
from doc_audit_agent.core.agents.figure_table_checker.agents import FigureTableAgents
from doc_audit_agent.core.agents.figure_table_checker.tasks import FigureTableTasks
import os
from dotenv import load_dotenv

load_dotenv()

class FigureTableCrew:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.agents = FigureTableAgents()
        self.tasks = FigureTableTasks()
        
        # Configure LLM
        api_key = os.getenv("ALIYUN_API_KEY")
        base_url = os.getenv("ALIYUN_API_BASE")
        model_name = os.getenv("MODEL_NAME", "qwen-plus")
        
        # Ensure model name has openai/ prefix if not present, as required by LiteLLM for compatible endpoints
        if not model_name.startswith("openai/"):
            model_name = f"openai/{model_name}"

        if not api_key:
             # Fallback to check if OPENAI_API_KEY is set, if not, raise error or let it fail naturally but with a better message if possible
             pass
        
        # Ensure OPENAI_API_KEY is set for CrewAI internal checks
        if "OPENAI_API_KEY" not in os.environ:
             os.environ["OPENAI_API_KEY"] = "NA"

        self.llm = LLM(
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            timeout=600  # Increase timeout to 10 minutes to prevent APITimeoutError
        )

    def run(self, step_callback=None, task_callback=None):
        # Create Agents
        processor = self.agents.document_processor_agent(self.llm, step_callback)
        analyzer_a = self.agents.content_analyzer_agent(self.llm, step_callback)
        analyzer_b = self.agents.content_analyzer_agent(self.llm, step_callback)
        verifier = self.agents.verification_agent(self.llm, step_callback)
        auditor = self.agents.auditor_agent(self.llm, step_callback)
        reviewer = self.agents.reviewer_agent(self.llm, step_callback)
        
        # Assign LLM to agents (Redundant but safe)
        processor.llm = self.llm
        analyzer_a.llm = self.llm
        analyzer_b.llm = self.llm
        verifier.llm = self.llm
        auditor.llm = self.llm
        reviewer.llm = self.llm

        # Create Tasks
        task1 = self.tasks.process_document_task(processor, self.pdf_path)
        task2_a = self.tasks.analyze_content_task(analyzer_a, task1)
        task2_b = self.tasks.analyze_content_task_b(analyzer_b, task1)
        task3 = self.tasks.verify_analysis_task(verifier, task2_a, task2_b)
        task4 = self.tasks.audit_content_task(auditor, task3)
        task5 = self.tasks.review_and_report_task(reviewer, task4)

        # Create Crew
        crew = Crew(
            agents=[processor, analyzer_a, analyzer_b, verifier, auditor, reviewer],
            tasks=[task1, task2_a, task2_b, task3, task4, task5],
            process=Process.sequential,
            verbose=True,
            memory=False,  # Disable memory to avoid permission issues in AppData
            step_callback=step_callback,
            task_callback=task_callback
        )

        result = crew.kickoff()
        return result

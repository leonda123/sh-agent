from crewai import Agent, LLM
from app.core.llm import LLMFactory
from app.tools.document_tools import ProcessDocumentTool, ReadFileTool
import os

class TermAuditRoles:
    def __init__(self, llm: LLM = None):
        self.llm = llm or LLMFactory.get_aliyun_llm()
        self.process_tool = ProcessDocumentTool()
        self.read_tool = ReadFileTool()

    def load_prompt(self, filename):
        path = os.path.join(os.path.dirname(__file__), "prompts", filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def document_processor(self, callback=None):
        return Agent(
            role='文档处理专家',
            goal='将PDF文档转换为高质量的Markdown格式',
            backstory=self.load_prompt("processor_backstory.md"),
            verbose=True,
            allow_delegation=False,
            llm=self.llm,
            tools=[self.process_tool],
            step_callback=callback
        )

    def term_extractor(self, callback=None):
        return Agent(
            role='术语提取员',
            goal='从文档中提取所有定义的术语和缩略语',
            backstory=self.load_prompt("extractor_backstory.md"),
            verbose=True,
            allow_delegation=False,
            llm=self.llm,
            tools=[self.read_tool],
            step_callback=callback
        )

    def term_auditor(self, callback=None):
        return Agent(
            role='术语审计员',
            goal='提取文档中的术语和缩略语，并在正文中核查其使用情况',
            backstory=self.load_prompt("auditor_backstory.md"),
            verbose=True,
            allow_delegation=False,
            llm=self.llm,
            tools=[self.read_tool],
            step_callback=callback
        )

    def term_verifier(self, callback=None):
        return Agent(
            role='零引用复核员',
            goal='对初审未在正文中出现的术语进行独立复核',
            backstory=self.load_prompt("verifier_backstory.md"),
            verbose=True,
            allow_delegation=False,
            llm=self.llm,
            tools=[self.read_tool],
            step_callback=callback
        )

    def report_generator(self, callback=None):
        return Agent(
            role='报告生成员',
            goal='汇总审计结果，生成结构清晰的Markdown报告',
            backstory=self.load_prompt("reporter_backstory.md"),
            verbose=True,
            allow_delegation=False,
            llm=self.llm,
            step_callback=callback
        )

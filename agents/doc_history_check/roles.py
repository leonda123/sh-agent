import os
from crewai import Agent
from app.tools.document_tools import ProcessDocumentTool, ReadFileTool

class DocHistoryRoles:
    def __init__(self):
        self.process_tool = ProcessDocumentTool()
        self.read_tool = ReadFileTool()

    def load_prompt(self, filename):
        path = os.path.join(os.path.dirname(__file__), "prompts", filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def document_processor_agent(self, llm, callback=None):
        return Agent(
            role='文档处理专家',
            goal='将上传的 PDF 转换为适合分析的格式。',
            backstory=self.load_prompt("processor_backstory.md"),
            tools=[self.process_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def content_analyzer_agent(self, llm, callback=None):
        return Agent(
            role='内容分析师',
            goal='分析文档前几页的内容，提取并比对历史版本记录信息。',
            backstory=self.load_prompt("analyzer_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def verification_agent(self, llm, callback=None):
        return Agent(
            role='交叉验证员',
            goal='比对两份独立的分析报告，消除分歧，生成最终的无争议数据。',
            backstory=self.load_prompt("verifier_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def reviewer_agent(self, llm, callback=None):
        return Agent(
            role='审查员',
            goal='根据最终验证后的版本历史记录数据，结合规则进行判断并生成最终 Markdown 报告。',
            backstory=self.load_prompt("reviewer_backstory.md"),
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

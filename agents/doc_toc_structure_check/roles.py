import os
from crewai import Agent
from app.tools.document_tools import ProcessDocumentTool, ReadFileTool

class TOCStructureRoles:
    def __init__(self):
        self.process_tool = ProcessDocumentTool()
        self.read_tool = ReadFileTool()

    def load_prompt(self, filename):
        path = os.path.join(os.path.dirname(__file__), "prompts", filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def document_parser_agent(self, llm, callback=None):
        return Agent(
            role='文档解析专家',
            goal='对PDF进行结构化解析，提取每一页的页面内容、章节标题、页码标识和目录页内容。',
            backstory=self.load_prompt("parser_backstory.md"),
            tools=[self.process_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def toc_checker_a_agent(self, llm, callback=None):
        return Agent(
            role='A轮目录检查专家',
            goal='独立提取目录信息，识别章节名称、目录页码、实际页码，生成目录检查表。',
            backstory=self.load_prompt("toc_checker_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def toc_checker_b_agent(self, llm, callback=None):
        return Agent(
            role='B轮目录检查专家',
            goal='独立提取目录信息，识别章节名称、目录页码、实际页码，生成目录检查表。与A轮结果进行交叉验证。',
            backstory=self.load_prompt("toc_checker_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def cross_validator_agent(self, llm, callback=None):
        return Agent(
            role='交叉验证专家',
            goal='对比A轮和B轮的检查结果，生成最终的目录差异性检查结果表，确保结果准确可靠。',
            backstory=self.load_prompt("validator_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

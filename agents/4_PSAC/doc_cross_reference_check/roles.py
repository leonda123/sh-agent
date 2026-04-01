import os
from crewai import Agent
from .cross_reference_tools import (
    ProcessDocumentTool,
    ReadFileTool,
    ReadPagesTool,
    FullTextSearchTool,
    PageByPageSearchTool,
)


class CrossReferenceRoles:
    def __init__(self):
        self.process_tool = ProcessDocumentTool()
        self.read_tool = ReadFileTool()
        self.read_pages_tool = ReadPagesTool()
        self.full_text_search_tool = FullTextSearchTool()
        self.page_by_page_search_tool = PageByPageSearchTool()

    def load_prompt(self, filename):
        path = os.path.join(os.path.dirname(__file__), "prompts", filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def document_parser_agent(self, llm, callback=None):
        return Agent(
            role='文档解析员',
            goal='将上传的PDF转换为Markdown格式，提取全文文本和逐页文本。',
            backstory=self.load_prompt("parser_backstory.md"),
            tools=[self.process_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def a_round_checker_agent(self, llm, callback=None):
        return Agent(
            role='A轮核验员',
            goal='基于全文文本进行精确检索，输出是否命中、命中次数、命中页码和原文依据。',
            backstory=self.load_prompt("a_round_checker_backstory.md"),
            tools=[self.read_tool, self.full_text_search_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def b_round_checker_agent(self, llm, callback=None):
        return Agent(
            role='B轮核验员',
            goal='基于逐页文本独立检索，重点复核是否存在漏检页、命中次数是否统计一致、命中页码是否统计一致。',
            backstory=self.load_prompt("b_round_checker_backstory.md"),
            tools=[self.read_pages_tool, self.page_by_page_search_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def cross_validator_agent(self, llm, callback=None):
        return Agent(
            role='交叉验证员',
            goal='对A轮与B轮的差异项进行复核，若结果不一致必须回到原文逐页确认，输出最终统一的检索结果和审查结论。',
            backstory=self.load_prompt("cross_validator_backstory.md"),
            tools=[self.read_tool, self.read_pages_tool, self.full_text_search_tool, self.page_by_page_search_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def report_generator_agent(self, llm, callback=None):
        return Agent(
            role='报告生成员',
            goal='输出前端可直接展示的固定结构结果，包含审查任务信息、审查结果、审查依据、检索结果、判定说明等区域。',
            backstory=self.load_prompt("report_generator_backstory.md"),
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

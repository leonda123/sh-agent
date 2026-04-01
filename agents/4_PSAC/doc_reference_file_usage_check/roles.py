import os
from crewai import Agent
from app.tools.document_tools import ProcessDocumentTool, ReadFileTool

class ReferenceFileRoles:
    def __init__(self):
        self.process_tool = ProcessDocumentTool()
        self.read_tool = ReadFileTool()

    def load_prompt(self, filename):
        path = os.path.join(os.path.dirname(__file__), "prompts", filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def document_parser_agent(self, llm, callback=None):
        return Agent(
            role='文档解析员',
            goal='将上传的PDF转换为Markdown格式，提取全文文本和章节结构。',
            backstory=self.load_prompt("parser_backstory.md"),
            tools=[self.process_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def reference_file_extractor_agent(self, llm, callback=None):
        return Agent(
            role='引用文件提取员',
            goal='定位"引用文件"或"参考文件"章节，提取各个文件的文件编号/文件标识和文件名称。',
            backstory=self.load_prompt("extractor_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def a_round_checker_agent(self, llm, callback=None):
        return Agent(
            role='A轮核验员',
            goal='核验各文件是否在正文中至少出现两次，输出每个文件的命中次数、命中页码和原文依据。',
            backstory=self.load_prompt("a_round_checker_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def b_round_checker_agent(self, llm, callback=None):
        return Agent(
            role='B轮核验员',
            goal='独立复核文件提取和正文命中次数，重点复核文件编号/文件标识是否提取正确、正文命中次数是否统计正确、是否误把"引用文件"章节本身计入正文命中次数。',
            backstory=self.load_prompt("b_round_checker_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def cross_validator_agent(self, llm, callback=None):
        return Agent(
            role='交叉验证员',
            goal='对A轮与B轮的差异项进行复核，若A轮与B轮结果不一致，必须回到原文重新确认，输出最终有效结果和异常文件清单。',
            backstory=self.load_prompt("cross_validator_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def report_generator_agent(self, llm, callback=None):
        return Agent(
            role='报告生成员',
            goal='输出固定结构HTML报告，包含审查任务信息、审查结果、审查依据、引用文件提取结果、核验结果、异常项、判定说明等区域。',
            backstory=self.load_prompt("report_generator_backstory.md"),
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

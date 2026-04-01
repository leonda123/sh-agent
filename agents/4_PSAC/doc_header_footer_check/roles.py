import os
from crewai import Agent
from .tools import ExtractHeaderFooterJsonTool, ReadHeaderFooterJsonTool


class HeaderFooterRoles:
    def __init__(self):
        self.extract_tool = ExtractHeaderFooterJsonTool()
        self.read_tool = ReadHeaderFooterJsonTool()

    def load_prompt(self, filename):
        path = os.path.join(os.path.dirname(__file__), "prompts", filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def parser_agent(self, llm, callback=None):
        return Agent(
            role='文档解析员',
            goal='使用专用工具从 PDF 原文件逐页提取页眉、页脚、页码信息，生成 header_footer.json 文件。',
            backstory=self.load_prompt("parser_backstory.md"),
            tools=[self.extract_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def baseline_extractor_agent(self, llm, callback=None):
        return Agent(
            role='基准提取员',
            goal='从 header_footer.json 中提取首页基准信息（文件编号、文件版本），作为后续一致性校验基准。',
            backstory=self.load_prompt("baseline_extractor_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

    def header_footer_identifier_agent(self, llm, callback=None):
        return Agent(
            role='页眉页脚识别员',
            goal='基于 header_footer.json 识别各页页眉页脚内容，区分正文页与非正文页，输出结构化识别结果。',
            backstory=self.load_prompt("header_footer_identifier_backstory.md"),
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
            goal='逐页检查正文页页眉是否包含文件编号和文件版本，页脚是否包含版权信息和页码。',
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
            goal='独立复核正文页页眉与首页基准一致性，页脚版权信息表述，以及页码连续性。',
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
            goal='比对 A轮与B轮核验结果，对差异项回到原文复核，输出最终异常页清单和判定。',
            backstory=self.load_prompt("cross_validator_backstory.md"),
            tools=[self.read_tool],
            verbose=True,
            memory=False,
            max_iter=5,
            llm=llm,
            step_callback=callback
        )

    def report_generator_agent(self, llm, callback=None):
        return Agent(
            role='报告生成员',
            goal='基于交叉验证结果，生成专业级的页眉页脚完整性审查报告，包含明确结论和原文依据。',
            backstory=self.load_prompt("report_generator_backstory.md"),
            verbose=True,
            memory=False,
            max_iter=3,
            llm=llm,
            step_callback=callback
        )

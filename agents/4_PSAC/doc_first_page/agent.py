import json
import litellm
import os
import re
from queue import Queue
from threading import Event
from typing import Any, Dict, List, Optional

from .roles import FirstPageAuditRoles
from .tasks import FirstPageAuditTasks
from app.core.base_agent import BaseAgent
from app.tools.document_tools import ProcessDocumentTool


class DocFirstPageAgent(BaseAgent):
    FIELD_ORDER = [
        "file_name",
        "file_number",
        "version",
        "publish_date",
        "copyright_statement",
    ]

    FIELD_LABELS = {
        "file_name": "文件名称",
        "file_number": "文件编号",
        "version": "版本",
        "publish_date": "文件发布日期",
        "copyright_statement": "版权声明",
    }

    TITLE_KEYWORDS = (
        "计划",
        "标准",
        "规范",
        "规程",
        "程序",
        "制度",
        "办法",
        "方案",
        "导则",
        "指南",
        "要求",
        "手册",
        "细则",
        "大纲",
        "报告",
        "流程",
    )

    TITLE_EXCLUSION_KEYWORDS = (
        "文件编号",
        "文件名称",
        "版本",
        "发布日期",
        "版本记录",
        "修订记录",
        "审批记录",
        "版权",
        "版权所有",
        "copyright",
        "all rights reserved",
        "总页数",
    )

    COPYRIGHT_KEYWORDS = (
        "©",
        "版权所有",
        "copyright",
        "all rights reserved",
        "知识产权",
        "未经许可",
        "侵权必究",
        "intellectual property",
    )

    def __init__(self):
        self.roles = FirstPageAuditRoles()
        self.tasks = FirstPageAuditTasks()
        self.phase_llms = {
            "phase_1": self.roles.get_llm_for_phase("phase_1"),
            "phase_2": self.roles.get_llm_for_phase("phase_2"),
            "phase_3": self.roles.get_llm_for_phase("phase_3"),
        }

    @property
    def name(self) -> str:
        return "doc_first_page"

    @property
    def display_name(self) -> str:
        return "文档首页要素审查"

    @property
    def description(self) -> str:
        return "检查首页是否包含文件名称、文件编号、版本、文件发布日期与版权声明。"

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
                "item_no": "1",
                "content": "首页是否包含了文件名称、文件编号、版本、文件发布日期以及版权声明？",
            }
        ]

    @property
    def phase_definitions(self) -> List[Dict[str, str]]:
        return [
            {"id": "phase_1", "label": "首页解析"},
            {"id": "phase_2", "label": "字段提取"},
            {"id": "phase_3", "label": "结论总结"},
        ]

    @property
    def phase_task_requirements(self) -> Dict[str, int]:
        return {
            "phase_1": 1,
            "phase_2": 1,
            "phase_3": 1,
        }

    @property
    def role_phase_map(self) -> Dict[str, str]:
        return {
            "文档解析员": "phase_1",
            "首页要素提取员": "phase_2",
            "结论生成员": "phase_3",
        }

    @property
    def min_file_count(self) -> int:
        return 1

    @property
    def max_file_count(self) -> Optional[int]:
        return 1

    def _ensure_not_stopped(self, stop_event: Event):
        if stop_event.is_set():
            raise RuntimeError("Audit stopped by user.")

    def _emit_step(
        self,
        queue: Queue,
        agent: str,
        phase_id: str,
        content: str,
        thought: str,
    ):
        queue.put(
            {
                "type": "step",
                "agent": agent,
                "phase_id": phase_id,
                "content": content,
                "thought": thought,
            }
        )

    def _emit_task_completed(self, queue: Queue, agent: str, phase_id: str, description: str):
        queue.put(
            {
                "type": "task_completed",
                "data": {
                    "phase_id": phase_id,
                    "agent": agent,
                    "description": description,
                },
            }
        )

    def _process_input_file(self, input_path: str) -> str:
        if input_path.lower().endswith(".md"):
            return input_path
        processor = ProcessDocumentTool()
        result = processor._run(input_path)
        if not result.lower().endswith(".md"):
            raise RuntimeError(result)
        return result

    def _page_json_path(self, markdown_path: str) -> str:
        base_path, _ = os.path.splitext(markdown_path)
        return f"{base_path}.pages.json"

    def _load_page_payload(self, markdown_path: str) -> Dict[str, Any]:
        page_json_path = self._page_json_path(markdown_path)
        if not os.path.exists(page_json_path):
            return {}
        with open(page_json_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _read_markdown_lines(self, markdown_path: str) -> List[str]:
        with open(markdown_path, "r", encoding="utf-8") as file:
            return file.read().splitlines()

    def _slice_first_page(self, markdown_lines: List[str], page_payload: Dict[str, Any]) -> Dict[str, Any]:
        pages = page_payload.get("pages") or []
        if pages:
            first_page = pages[0]
            return {
                "text": first_page.get("page_content", "").strip(),
                "page_label": first_page.get("page_label") or "1",
                "start_line": first_page.get("content_start_line") or 1,
                "end_line": first_page.get("content_end_line") or len(markdown_lines),
                "source": "pages.json",
            }

        trailing = page_payload.get("trailing_unassigned_content") or {}
        if trailing.get("page_content"):
            end_line = min((trailing.get("content_end_line") or len(markdown_lines)), 120)
            start_line = trailing.get("content_start_line") or 1
            text = "\n".join(markdown_lines[start_line - 1:end_line]).strip()
            return {
                "text": text,
                "page_label": "1",
                "start_line": start_line,
                "end_line": end_line,
                "source": "markdown-leading-lines",
            }

        end_line = min(len(markdown_lines), 120)
        return {
            "text": "\n".join(markdown_lines[:end_line]).strip(),
            "page_label": "1",
            "start_line": 1,
            "end_line": end_line,
            "source": "markdown-leading-lines",
        }

    def _clean_line(self, line: str) -> str:
        cleaned = self._normalize_escaped_text(line.strip())
        cleaned = re.sub(r"^[#>\-\*\d\.\)\(]+\s*", "", cleaned)
        cleaned = cleaned.strip("|").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _normalize_escaped_text(self, text: str) -> str:
        return re.sub(r"\\([\-./:|])", r"\1", text)

    def _is_table_separator(self, line: str) -> bool:
        stripped = line.strip()
        return bool(stripped) and all(char in "-|: " for char in stripped)

    def _looks_like_title(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        if any(keyword.lower() in lowered for keyword in self.TITLE_EXCLUSION_KEYWORDS):
            return False
        if re.fullmatch(r"[0-9IVXLCDM\.\-_/ ]+", text, flags=re.IGNORECASE):
            return False
        if len(text) < 4 or len(text) > 80:
            return False
        if text.count("|") >= 2:
            return False
        if re.search(r"\d{4}[-/年]\d{1,2}", text):
            return False
        if any(keyword in text for keyword in self.TITLE_KEYWORDS):
            return True
        return bool(re.search(r"[\u4e00-\u9fffA-Za-z]{4,}", text))

    def _detect_file_name(self, lines: List[str], line_offset: int) -> Dict[str, Any]:
        explicit_match = self._match_line_patterns(
            lines,
            [
                re.compile(r"(?:文件名称|文档名称|标题)\s*[:：|]\s*(.+)"),
                re.compile(r"\|\s*(?:文件名称|文档名称|标题)\s*\|\s*([^|]+?)\s*\|"),
            ],
            line_offset,
            "文件名称标签识别",
        )
        if explicit_match["present"]:
            return explicit_match

        for index, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if not stripped or self._is_table_separator(stripped):
                continue
            heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", stripped)
            candidate = self._clean_line(heading_match.group(1) if heading_match else stripped)
            if self._looks_like_title(candidate):
                return {
                    "present": True,
                    "value": candidate,
                    "evidence": candidate,
                    "line": line_offset + index - 1,
                    "rule": "首页一级标题/主标题识别",
                }

        for index, raw_line in enumerate(lines[:20], start=1):
            candidate = self._clean_line(raw_line)
            if self._looks_like_title(candidate):
                return {
                    "present": True,
                    "value": candidate,
                    "evidence": candidate,
                    "line": line_offset + index - 1,
                    "rule": "首页主标题兜底识别",
                }

        return {
            "present": False,
            "value": "",
            "evidence": "未识别到可判定的首页一级标题或主标题",
            "line": None,
            "rule": "首页一级标题/主标题识别",
        }

    def _match_line_patterns(
        self,
        lines: List[str],
        patterns: List[re.Pattern],
        line_offset: int,
        rule: str,
    ) -> Dict[str, Any]:
        for index, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            normalized = self._normalize_escaped_text(stripped)
            for pattern in patterns:
                match = pattern.search(normalized)
                if match:
                    value = self._normalize_escaped_text(match.group(1)).strip(" ：:|")
                    return {
                        "present": True,
                        "value": value,
                        "evidence": stripped,
                        "line": line_offset + index - 1,
                        "rule": rule,
                    }

        return {
            "present": False,
            "value": "",
            "evidence": f"首页未发现满足规则“{rule}”的内容",
            "line": None,
            "rule": rule,
        }

    def _detect_file_number(self, lines: List[str], line_offset: int) -> Dict[str, Any]:
        patterns = [
            re.compile(r"(?:文件编号|文档编号|文件代号|编号)\s*[:：|]\s*([A-Za-z0-9./\-_()（）]+)"),
            re.compile(r"\|\s*(?:文件编号|文档编号|文件代号|编号)\s*\|\s*([^|]+?)\s*\|"),
        ]
        return self._match_line_patterns(lines, patterns, line_offset, "标签字段识别")

    def _detect_version(self, lines: List[str], line_offset: int) -> Dict[str, Any]:
        patterns = [
            re.compile(r"(?:版本(?:号)?|版次|修订版|revision|rev\.?)\s*[:：|]?\s*([A-Za-z0-9./\-_()（）]+)", flags=re.IGNORECASE),
            re.compile(r"\|\s*(?:版本(?:号)?|版次|修订版|Revision|REV)\s*\|\s*([^|]+?)\s*\|", flags=re.IGNORECASE),
        ]
        return self._match_line_patterns(lines, patterns, line_offset, "版本字段识别")

    def _detect_publish_date(self, lines: List[str], line_offset: int) -> Dict[str, Any]:
        date_pattern = re.compile(r"\d{4}\s*[年./-]\s*\d{1,2}(?:\s*[月./-]\s*\d{1,2}\s*日?)?")
        keywords = ("文件发布日期", "发布日期", "生效日期", "发布时间")

        for index, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            normalized = self._normalize_escaped_text(stripped)

            if "|" in normalized:
                cells = [cell.strip() for cell in normalized.strip("|").split("|")]
                if len(cells) >= 2 and any(keyword in cells[0] for keyword in keywords):
                    date_match = date_pattern.search(cells[1])
                    if date_match:
                        return {
                            "present": True,
                            "value": date_match.group(0).strip(),
                            "evidence": stripped,
                            "line": line_offset + index - 1,
                            "rule": "发布日期字段识别",
                        }

            if any(keyword in normalized for keyword in keywords):
                date_match = date_pattern.search(normalized)
                if date_match:
                    return {
                        "present": True,
                        "value": date_match.group(0).strip(),
                        "evidence": stripped,
                        "line": line_offset + index - 1,
                        "rule": "发布日期字段识别",
                    }

        return {
            "present": False,
            "value": "",
            "evidence": "首页未发现满足规则“发布日期字段识别”的内容",
            "line": None,
            "rule": "发布日期字段识别",
        }

    def _detect_copyright(self, lines: List[str], line_offset: int) -> Dict[str, Any]:
        for index, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            lowered = stripped.lower()
            if any(keyword.lower() in lowered for keyword in self.COPYRIGHT_KEYWORDS):
                return {
                    "present": True,
                    "value": self._clean_line(stripped),
                    "evidence": stripped,
                    "line": line_offset + index - 1,
                    "rule": "版权关键词识别",
                }

        return {
            "present": False,
            "value": "",
            "evidence": "首页未识别到版权关键词",
            "line": None,
            "rule": "版权关键词识别",
        }

    def _evaluate_first_page_fields(self, first_page: Dict[str, Any]) -> Dict[str, Any]:
        text = first_page.get("text", "")
        lines = text.splitlines()
        line_offset = first_page.get("start_line", 1)

        fields = {
            "file_name": self._detect_file_name(lines, line_offset),
            "file_number": self._detect_file_number(lines, line_offset),
            "version": self._detect_version(lines, line_offset),
            "publish_date": self._detect_publish_date(lines, line_offset),
            "copyright_statement": self._detect_copyright(lines, line_offset),
        }

        missing_fields = [
            self.FIELD_LABELS[field_name]
            for field_name in self.FIELD_ORDER
            if not fields[field_name]["present"]
        ]

        audit_result = "通过" if not missing_fields else "不通过"
        key_finding = (
            "首页已包含全部必检字段。"
            if not missing_fields
            else f"首页缺少以下字段：{'、'.join(missing_fields)}。"
        )

        return {
            "fields": fields,
            "missing_fields": missing_fields,
            "audit_result": audit_result,
            "finding_conclusion": audit_result,
            "key_finding": key_finding,
        }

    def _build_field_table(self, conclusion: Dict[str, Any]) -> str:
        lines = [
            "## 首页字段检查明细",
            "",
            "| 字段 | 检查结果 | 提取值 | 证据 | 识别规则 |",
            "| --- | --- | --- | --- | --- |",
        ]

        for field_name in self.FIELD_ORDER:
            field = conclusion["fields"][field_name]
            status = "存在" if field["present"] else "缺失"
            value = self._format_table_cell(field["value"] or "-")
            evidence = self._format_table_cell(field["evidence"])
            if field.get("line"):
                evidence = self._format_table_cell(f'line {field["line"]}: {field["evidence"]}')
            rule = self._format_table_cell(field["rule"])
            lines.append(
                f"| {self.FIELD_LABELS[field_name]} | {status} | {value} | {evidence} | {rule} |"
            )

        return "\n".join(lines)

    def _format_table_cell(self, value: str) -> str:
        normalized = str(value or "-").replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("|", "\\|")
        normalized = normalized.replace("\n", "<br>")
        return normalized

    def _build_first_page_section(self, first_page: Dict[str, Any]) -> str:
        preview = first_page.get("text", "").strip()
        if len(preview) > 1200:
            preview = preview[:1200].rstrip() + "..."

        return "\n".join(
            [
                "## 首页定位",
                "",
                "| 项目 | 详情 |",
                "| --- | --- |",
                f'| 首页来源 | {first_page.get("source", "-")} |',
                f'| 页码标签 | {first_page.get("page_label", "-")} |',
                f'| 行范围 | line {first_page.get("start_line", 1)} 到 line {first_page.get("end_line", 1)} |',
                "",
                "## 首页原文摘录",
                "",
                "```text",
                preview,
                "```",
            ]
        )

    def _build_summary_section(self, conclusion: Dict[str, Any], first_page: Dict[str, Any]) -> str:
        missing_fields = "无" if not conclusion["missing_fields"] else "、".join(conclusion["missing_fields"])
        return "\n".join(
            [
                "## 审计综述",
                "",
                "| 项目 | 详情 |",
                "| --- | --- |",
                f'| 检查范围 | 首页字段完整性审查 |',
                f'| 审计结果 | **{conclusion["audit_result"]}** |',
                f'| 检查项最终结论 | **{conclusion["finding_conclusion"]}** |',
                f'| 首页页码 | {first_page.get("page_label", "-")} |',
                f'| 缺失字段 | {missing_fields} |',
                f'| 关键发现 | {conclusion["key_finding"]} |',
            ]
        )

    def _build_report(self, markdown_path: str, first_page: Dict[str, Any], conclusion: Dict[str, Any]) -> str:
        return "\n\n".join(
            [
                "# 文档首页要素审查报告",
                self._build_summary_section(conclusion, first_page),
                self._build_field_table(conclusion),
                self._build_first_page_section(first_page),
                "\n".join(
                    [
                        "## 结论说明",
                        "",
                        "本次审查仅针对上传文档首页进行规则核查，判断首页是否包含以下五项内容：文件名称、文件编号、版本、文件发布日期、版权声明。",
                        f'最终结论：**{conclusion["finding_conclusion"]}**。',
                        f'结论依据：{conclusion["key_finding"]}',
                        f"Markdown 文件：{markdown_path}",
                    ]
                ),
            ]
        )

    def _build_llm_field_brief(self, conclusion: Dict[str, Any]) -> str:
        rows = []
        for field_name in self.FIELD_ORDER:
            field = conclusion["fields"][field_name]
            status = "存在" if field["present"] else "缺失"
            value = field["value"] or "-"
            rows.append(f"- {self.FIELD_LABELS[field_name]}：{status}；提取值：{value}；证据：{field['evidence']}")
        return "\n".join(rows)

    def _invoke_phase_llm(self, phase_id: str, agent_role: str, prompt: str, stop_event: Event) -> str:
        self._ensure_not_stopped(stop_event)
        llm = self.phase_llms[phase_id]
        response = litellm.completion(
            model=getattr(llm, "model", os.getenv("MODEL_NAME", "openai/qwen3.5-flash")),
            api_key=getattr(llm, "api_key", os.getenv("ALIYUN_API_KEY")),
            base_url=getattr(llm, "base_url", os.getenv("ALIYUN_API_BASE")),
            temperature=getattr(llm, "temperature", 0.2),
            timeout=getattr(llm, "timeout", 600),
            messages=[
                {
                    "role": "system",
                    "content": f"You are {agent_role}.\n{self.roles.get_role_prompt(agent_role)}\n请仅基于提供内容输出简洁结论，不要编造未出现的信息。",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        choice = response.choices[0].message
        content = choice.content if hasattr(choice, "content") else choice.get("content", "")
        return (content or "").strip()

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        input_file = self.get_primary_input_file(inputs)
        input_path = input_file.get("path")

        self._ensure_not_stopped(stop_event)
        markdown_path = self._process_input_file(input_path)
        page_payload = self._load_page_payload(markdown_path)
        markdown_lines = self._read_markdown_lines(markdown_path)
        first_page = self._slice_first_page(markdown_lines, page_payload)

        parser_model = getattr(self.phase_llms["phase_1"], "model", "default")
        parser_prompt = self.roles.get_role_prompt("文档解析员")
        self._emit_step(
            queue,
            "文档解析员",
            "phase_1",
            f"首页解析完成，已定位 Markdown 首页范围（模型：{parser_model}）。",
            f'{self.tasks.parse_document_task(input_path)}\n首页来源：{first_page["source"]}\n首页范围：line {first_page["start_line"]} 到 line {first_page["end_line"]}\n角色提示：{parser_prompt}',
        )
        self._emit_task_completed(
            queue,
            "文档解析员",
            "phase_1",
            f"已完成首页定位并准备字段提取，Markdown 文件：{markdown_path}",
        )

        self._ensure_not_stopped(stop_event)
        conclusion = self._evaluate_first_page_fields(first_page)
        extractor_model = getattr(self.phase_llms["phase_2"], "model", "default")
        extractor_prompt = self.roles.get_role_prompt("首页要素提取员")
        detected_count = sum(1 for field in conclusion["fields"].values() if field["present"])
        extractor_llm_summary = ""
        try:
            extractor_llm_summary = self._invoke_phase_llm(
                "phase_2",
                "首页要素提取员",
                "\n".join(
                    [
                        self.tasks.extract_fields_task(),
                        "请基于以下首页摘录，用 3-5 行总结各字段命中情况，并特别指出缺失字段。",
                        "首页原文：",
                        first_page.get("text", "")[:1800],
                        "规则提取结果：",
                        self._build_llm_field_brief(conclusion),
                    ]
                ),
                stop_event,
            )
        except Exception as error:
            extractor_llm_summary = f"LLM 交互失败，已回退为规则结果：{error}"
        self._emit_step(
            queue,
            "首页要素提取员",
            "phase_2",
            f"首页字段提取完成，识别到 {detected_count}/5 个必检字段（模型：{extractor_model}）。",
            f'{self.tasks.extract_fields_task()}\n缺失字段：{"无" if not conclusion["missing_fields"] else "、".join(conclusion["missing_fields"])}\nLLM 提炼：{extractor_llm_summary}\n角色提示：{extractor_prompt}',
        )
        self._emit_task_completed(
            queue,
            "首页要素提取员",
            "phase_2",
            "已完成首页字段检查并生成结构化结论。",
        )

        self._ensure_not_stopped(stop_event)
        report = self._build_report(markdown_path, first_page, conclusion)
        reporter_model = getattr(self.phase_llms["phase_3"], "model", "default")
        reporter_prompt = self.roles.get_role_prompt("结论生成员")
        reporter_llm_summary = ""
        try:
            reporter_llm_summary = self._invoke_phase_llm(
                "phase_3",
                "结论生成员",
                "\n".join(
                    [
                        self.tasks.summarize_task(),
                        f'审计结果：{conclusion["audit_result"]}',
                        f'检查项最终结论：{conclusion["finding_conclusion"]}',
                        f'关键发现：{conclusion["key_finding"]}',
                        f'缺失字段：{"无" if not conclusion["missing_fields"] else "、".join(conclusion["missing_fields"])}',
                        "请输出简洁的结论摘要，明确说明首页是否通过检查。",
                    ]
                ),
                stop_event,
            )
        except Exception as error:
            reporter_llm_summary = f"LLM 交互失败，已使用规则结论直接生成报告：{error}"
        self._emit_step(
            queue,
            "结论生成员",
            "phase_3",
            f'报告生成完成，最终结论：{conclusion["finding_conclusion"]}（模型：{reporter_model}）。',
            f'{self.tasks.summarize_task()}\n{conclusion["key_finding"]}\nLLM 提炼：{reporter_llm_summary}\n角色提示：{reporter_prompt}',
        )
        self._emit_task_completed(
            queue,
            "结论生成员",
            "phase_3",
            f'已输出首页审查报告，最终结论：{conclusion["finding_conclusion"]}',
        )

        return report

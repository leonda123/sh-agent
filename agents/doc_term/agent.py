import os
import re
from queue import Queue
from threading import Event
from typing import Any, Dict, List

from crewai import Crew, Process
from dotenv import load_dotenv

from agents.doc_term.roles import TermAuditRoles
from agents.doc_term.tasks import TermAuditTasks
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
from app.tools.document_tools import ProcessDocumentTool

load_dotenv()

class DocTermAgent(BaseAgent):
    PHASE_MAP = {
        "文档处理专家": "phase_1",
        "术语提取员": "phase_2",
        "术语审计员": "phase_3",
        "零引用复核员": "phase_4",
        "报告生成员": "phase_5",
    }

    @property
    def name(self) -> str:
        return "doc_term"

    @property
    def display_name(self) -> str:
        return "术语/缩略语一致性审计"

    @property
    def description(self) -> str:
        return "检查文档中是否包含术语/缩略语章节，并核实其定义与正文使用的一致性。"

    def _ensure_not_stopped(self, stop_event: Event) -> None:
        if stop_event.is_set():
            raise RuntimeError("Audit stopped by user.")

    def _heading_info(self, line: str) -> Dict[str, Any] | None:
        stripped = line.strip()
        if not stripped:
            return None
        if "..." in stripped or "……" in stripped:
            return None
        markdown_heading = re.match(r"^(#{1,6})\s+(.*\S)\s*$", stripped)
        if markdown_heading:
            return {
                "level": len(markdown_heading.group(1)),
                "title": markdown_heading.group(2).strip(),
            }
        numeric_heading = re.match(r"^(\d+(?:\\?\.\d+)*)\s+(.+?)\s*$", stripped)
        if not numeric_heading:
            return None
        number = numeric_heading.group(1).replace("\\.", ".")
        return {
            "level": len([part for part in number.split(".") if part]),
            "title": numeric_heading.group(2).strip(),
        }

    def _normalize_term(self, term: str) -> str:
        cleaned = term.strip().strip("：:;；,.，。")
        cleaned = cleaned.replace("\\-", "-").replace("\\.", ".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.lower()

    def _clean_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = cleaned.replace("\\-", "-").replace("\\.", ".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _compact_text(self, text: str) -> str:
        return re.sub(r"\s+", "", self._clean_text(text))

    def _is_separator_row(self, line: str) -> bool:
        return bool(re.match(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$", line))

    def _split_table_row(self, line: str) -> List[str]:
        stripped = line.strip().strip("|")
        return [self._clean_text(cell) for cell in stripped.split("|")]

    def _is_noise_text(self, text: str) -> bool:
        if not text:
            return True
        if "©" in text:
            return True
        if re.search(r"A\d{6,}", text):
            return True
        if text in {"AVICAS GENERIC TECHNOLOGY", "B"}:
            return True
        return False

    def _is_term_candidate(self, text: str) -> bool:
        if not text or self._is_noise_text(text):
            return False
        if len(text) > 80:
            return False
        if re.search(r"[。！？；;，,]", text):
            return False
        return True

    def _count_candidate_occurrences(self, lines: List[str], candidate: str, excluded_start: int, excluded_end: int) -> int:
        count = 0
        for line_number, raw_line in enumerate(lines, start=1):
            if excluded_start <= line_number <= excluded_end:
                continue
            clean_line = self._clean_text(raw_line)
            if not clean_line or self._is_noise_text(clean_line):
                continue
            if candidate in clean_line:
                count += 1
        return count

    def _recover_term_from_orphan_definition(
        self,
        line: str,
        full_lines: List[str],
        excluded_start: int,
        excluded_end: int,
    ) -> str | None:
        compact_line = re.sub(r"\s+", "", line)
        priority_patterns = [
            r"中([\u4e00-\u9fff]{2,8})的错误",
            r"([\u4e00-\u9fff]{2,8})等级分配报告",
            r"对([\u4e00-\u9fff]{2,8})的要求",
        ]
        for pattern in priority_patterns:
            matched = re.search(pattern, compact_line)
            if not matched:
                continue
            candidate = matched.group(1)
            if self._count_candidate_occurrences(full_lines, candidate, excluded_start, excluded_end) >= 2:
                return candidate

        chinese_segments = re.findall(r"[\u4e00-\u9fff]{2,20}", compact_line)
        if not chinese_segments:
            return None

        stopwords = {
            "足够",
            "置信度",
            "水平",
            "所有",
            "证明",
            "需求",
            "设计",
            "实现",
            "错误",
            "识别",
            "纠正",
            "系统",
            "满足",
            "适用",
            "认证",
            "基础",
            "采用",
            "计划",
            "过程",
            "功能",
            "活动",
            "数据",
            "软件",
            "文档",
            "内容",
            "项目",
            "要求",
        }

        ranked_candidates: List[tuple[int, int, str]] = []
        seen = set()
        for segment in chinese_segments:
            max_size = min(8, len(segment))
            for size in range(2, max_size + 1):
                for start in range(0, len(segment) - size + 1):
                    candidate = segment[start:start + size]
                    if candidate in seen or candidate in stopwords:
                        continue
                    seen.add(candidate)
                    occurrences = self._count_candidate_occurrences(
                        full_lines,
                        candidate,
                        excluded_start,
                        excluded_end,
                    )
                    if occurrences < 2:
                        continue
                    score = occurrences * 10 + len(candidate) * 5
                    ranked_candidates.append((score, len(candidate), candidate))

        if not ranked_candidates:
            return None

        ranked_candidates.sort(reverse=True)
        return ranked_candidates[0][2]

    def _deduplicate_terms(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            normalized = self._normalize_term(entry["term"])
            if not normalized:
                continue
            current = merged.get(normalized)
            if current is None:
                merged[normalized] = entry
                continue
            if len(entry["definition"]) > len(current["definition"]):
                current["definition"] = entry["definition"]
            current["line_start"] = min(current["line_start"], entry["line_start"])
            current["line_end"] = max(current["line_end"], entry["line_end"])
            current_sources = set(current.get("sources", []))
            current_sources.update(entry.get("sources", []))
            current["sources"] = sorted(current_sources)
        return sorted(merged.values(), key=lambda item: item["line_start"])

    def _is_latin_term(self, term: str) -> bool:
        return bool(re.search(r"[A-Za-z]", term))

    def _find_latin_matches(self, text: str, term: str) -> List[Dict[str, Any]]:
        normalized_term = self._compact_text(term).lower()
        matches: List[Dict[str, Any]] = []
        if not normalized_term:
            return matches

        for token_match in re.finditer(r"[A-Za-z0-9]+", text):
            token = token_match.group(0)
            token_lower = token.lower()
            matched = False

            if token_lower == normalized_term:
                matched = True
            elif token_lower.startswith(normalized_term) and token_lower[len(normalized_term):].isdigit():
                matched = True
            elif (
                len(normalized_term) >= 3
                and token.isupper()
                and token_lower.endswith(normalized_term)
                and 1 <= len(token) - len(normalized_term) <= 2
            ):
                matched = True

            if matched:
                matches.append(
                    {
                        "start": token_match.start(),
                        "end": token_match.end(),
                        "matched_text": token,
                        "search_mode": "latin_token",
                    }
                )
        return matches

    def _find_chinese_matches(self, text: str, term: str) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        search_start = 0
        while True:
            position = text.find(term, search_start)
            if position < 0:
                break
            matches.append(
                {
                    "start": position,
                    "end": position + len(term),
                    "matched_text": term,
                    "search_mode": "chinese_fulltext",
                }
            )
            search_start = position + len(term)
        return matches

    def _build_snippet(self, text: str, start: int, end: int, window: int = 10) -> str:
        left = max(0, start - window)
        right = min(len(text), end + window)
        return text[left:right]

    def _find_matches_in_line(self, text: str, term: str) -> List[Dict[str, Any]]:
        if self._is_latin_term(term):
            return self._find_latin_matches(text, term)
        return self._find_chinese_matches(text, term)

    def _collect_term_occurrences(self, lines: List[str], term: str, excluded_start: int, excluded_end: int) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        current_heading = "未识别章节"

        for line_number, raw_line in enumerate(lines, start=1):
            heading = self._heading_info(raw_line)
            if heading:
                current_heading = self._clean_text(heading["title"])
            if excluded_start <= line_number <= excluded_end:
                continue
            clean_line = self._clean_text(raw_line)
            if not clean_line or self._is_noise_text(clean_line):
                continue

            for match in self._find_matches_in_line(clean_line, term):
                results.append(
                    {
                        "line": line_number,
                        "heading": current_heading,
                        "snippet": self._build_snippet(clean_line, match["start"], match["end"], window=10),
                        "matched_text": match["matched_text"],
                        "search_mode": match["search_mode"],
                    }
                )
        return results

    def _build_retrieval_audit(self, seed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        audit_rows: List[Dict[str, Any]] = []
        for entry in seed_data["entries"]:
            occurrences = self._collect_term_occurrences(
                seed_data["lines"],
                entry["term"],
                seed_data["start_line"],
                seed_data["end_line"],
            )
            audit_rows.append(
                {
                    "term": entry["term"],
                    "definition": entry["definition"] or "定义缺失",
                    "count": len(occurrences),
                    "status": "正确" if occurrences else "错误",
                    "search_mode": occurrences[0]["search_mode"] if occurrences else ("latin_token" if self._is_latin_term(entry["term"]) else "chinese_fulltext"),
                    "evidence": occurrences,
                }
            )
        return audit_rows

    def _build_retrieval_context(self, retrieval_rows: List[Dict[str, Any]]) -> str:
        if not retrieval_rows:
            return "程序化检索未生成可用的引用基线。"

        lines = [
            "- 以下内容为程序化检索基线，请优先参考，不要自行猜测次数。",
            "- 检索规则：英文/缩略语采用分词检索；中文术语采用全文精确匹配。",
            "- 证据规则：每条证据保留命中位置前后各10个字作为原文出处。",
        ]
        for index, row in enumerate(retrieval_rows, start=1):
            evidence_items = row["evidence"][:4]
            evidence_text = "；".join(
                [
                    f'[{item["heading"]} / line {item["line"]}] {item["snippet"]}'
                    for item in evidence_items
                ]
            ) or "未检索到正文引用"
            lines.append(
                f'{index}. {row["term"]} | mode={row["search_mode"]} | count={row["count"]} | status={row["status"]} | evidence={evidence_text}'
            )
        return "\n".join(lines)

    def _find_glossary_section(self, lines: List[str]) -> Dict[str, Any]:
        headings: List[Dict[str, Any]] = []
        for index, line in enumerate(lines):
            info = self._heading_info(line)
            if not info:
                continue
            title = self._clean_text(info["title"])
            headings.append(
                {
                    "index": index,
                    "level": info["level"],
                    "title": title,
                }
            )

        root = None
        for heading in headings:
            title = heading["title"]
            if "术语" in title and ("缩略语" in title or "定义" in title):
                root = heading
                break

        if root is None:
            return {
                "start_index": 0,
                "end_index": 0,
                "start_marker": "",
                "end_marker": "",
                "title": "",
            }

        end_index = len(lines)
        for heading in headings:
            if heading["index"] <= root["index"]:
                continue
            if heading["level"] <= root["level"]:
                end_index = heading["index"]
                break

        return {
            "start_index": root["index"],
            "end_index": end_index,
            "start_marker": root["title"],
            "end_marker": headings[[item["index"] for item in headings].index(end_index)]["title"] if end_index in [item["index"] for item in headings] else "",
            "title": root["title"],
        }

    def _parse_seed_terms(self, markdown_path: str) -> Dict[str, Any]:
        with open(markdown_path, "r", encoding="utf-8") as file:
            lines = file.read().splitlines()

        glossary_section = self._find_glossary_section(lines)
        start_index = glossary_section["start_index"]
        end_index = glossary_section["end_index"]
        section_lines = lines[start_index:end_index] if glossary_section["title"] else []

        entries: List[Dict[str, Any]] = []
        last_entry: Dict[str, Any] | None = None

        for relative_index, raw_line in enumerate(section_lines):
            absolute_index = start_index + relative_index + 1
            line = raw_line.strip()
            if not line:
                continue
            if self._heading_info(line):
                last_entry = None
                continue
            if line.startswith("|"):
                if self._is_separator_row(line):
                    continue
                cells = [cell for cell in self._split_table_row(line) if cell]
                if not cells:
                    continue
                header_text = " ".join(cells[:2]).lower()
                if any(marker in header_text for marker in ("缩略语", "英文全称", "术语", "term", "abbreviation")):
                    continue
                term = cells[0]
                definition = " | ".join(cells[1:]).strip()
                if not self._is_term_candidate(term):
                    continue
                if not definition and len(cells) == 1:
                    continue
                last_entry = {
                    "term": self._clean_text(term),
                    "definition": self._clean_text(definition),
                    "line_start": absolute_index,
                    "line_end": absolute_index,
                    "sources": [f"line {absolute_index}"],
                }
                entries.append(last_entry)
                continue

            list_match = re.match(r"^(?:[-*]|\d+[.)、])\s*([^:：]{1,80})[:：]\s*(.+)$", line)
            if list_match:
                term = self._clean_text(list_match.group(1))
                definition = self._clean_text(list_match.group(2))
                if self._is_term_candidate(term):
                    last_entry = {
                        "term": term,
                        "definition": definition,
                        "line_start": absolute_index,
                        "line_end": absolute_index,
                        "sources": [f"line {absolute_index}"],
                    }
                    entries.append(last_entry)
                    continue

            recovered_term = self._recover_term_from_orphan_definition(
                line,
                lines,
                glossary_section["start_index"] + 1,
                glossary_section["end_index"],
            )
            if recovered_term:
                last_entry = {
                    "term": recovered_term,
                    "definition": self._clean_text(line),
                    "line_start": absolute_index,
                    "line_end": absolute_index,
                    "sources": [f"recovered line {absolute_index}"],
                }
                entries.append(last_entry)
                continue

            if last_entry and absolute_index - last_entry["line_end"] <= 3 and not self._is_noise_text(line):
                if not re.match(r"^\d+(?:\\?\.\d+)*\s+", line):
                    continuation = self._clean_text(line)
                    if continuation:
                        merged_definition = f'{last_entry["definition"]} {continuation}'.strip()
                        last_entry["definition"] = merged_definition
                        last_entry["line_end"] = absolute_index
                        last_entry["sources"].append(f"line {absolute_index}")
                        continue

            last_entry = None

        deduplicated_entries = self._deduplicate_terms(entries)
        return {
            "path": markdown_path,
            "title": glossary_section["title"],
            "start_line": glossary_section["start_index"] + 1 if glossary_section["title"] else 1,
            "end_line": glossary_section["end_index"] if glossary_section["title"] else len(lines),
            "start_marker": glossary_section["start_marker"],
            "end_marker": glossary_section["end_marker"],
            "entries": deduplicated_entries,
            "lines": lines,
        }

    def _build_seed_context(self, seed_data: Dict[str, Any]) -> str:
        entries = seed_data["entries"]
        if not entries:
            return "规则解析未识别到可用术语条目。"
        lines = [
            f'- Markdown 路径: {seed_data["path"]}',
            f'- 术语章节标题: {seed_data["title"] or "未定位到专门章节"}',
            f'- 术语章节范围: line {seed_data["start_line"]} 到 line {seed_data["end_line"]}',
        ]
        if seed_data["start_marker"]:
            lines.append(f'- Start Marker: {seed_data["start_marker"]}')
        if seed_data["end_marker"]:
            lines.append(f'- End Marker: {seed_data["end_marker"]}')
        lines.append(f'- 规则解析共提取 {len(entries)} 项，请将其视为最低覆盖集合：')
        for index, entry in enumerate(entries, start=1):
            lines.append(f'  {index}. {entry["term"]} => {entry["definition"] or "定义缺失"}')
        return "\n".join(lines)

    def _evaluate_audit_result(self, seed_data: Dict[str, Any], retrieval_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        missing_reference_terms = [row["term"] for row in retrieval_rows if row["count"] == 0]
        glossary_found = bool(seed_data["title"])
        entries_found = bool(seed_data["entries"])
        passed = glossary_found and entries_found and not missing_reference_terms

        if not glossary_found:
            key_finding = "未找到术语/缩略语章节，无法形成有效的术语定义基线。"
        elif not entries_found:
            key_finding = "已定位术语/缩略语章节，但未提取到有效术语条目。"
        elif missing_reference_terms:
            key_finding = f'存在已声明但未在正文引用的术语/缩略语：{", ".join(missing_reference_terms)}。'
        else:
            key_finding = f'共检查 {len(retrieval_rows)} 项术语/缩略语，均已在正文找到引用。'

        return {
            "passed": passed,
            "audit_result": "通过" if passed else "不通过",
            "finding_conclusion": "通过" if passed else "不通过",
            "key_finding": key_finding,
            "missing_reference_terms": missing_reference_terms,
            "glossary_found": glossary_found,
            "entries_found": entries_found,
            "term_count": len(seed_data["entries"]),
        }

    def _build_summary_section(self, conclusion: Dict[str, Any], seed_data: Dict[str, Any]) -> str:
        return "\n".join(
            [
                "## 审计综述",
                "",
                "| 项目 | 详情 |",
                "| --- | --- |",
                f'| 术语/缩略语章节 | {"存在" if conclusion["glossary_found"] else "缺失"} |',
                f'| 识别术语数量 | {conclusion["term_count"]} |',
                f'| 审计结果 | **{conclusion["audit_result"]}** |',
                f'| 检查项最终结论 | **{conclusion["finding_conclusion"]}** |',
                f'| 关键发现 | {conclusion["key_finding"]} |',
                f'| 术语章节范围 | line {seed_data["start_line"]} 到 line {seed_data["end_line"]} |',
            ]
        )

    def _build_final_conclusion_section(self, conclusion: Dict[str, Any]) -> str:
        section_lines = [
            "## 检查项最终结论",
            "",
            f'**{conclusion["finding_conclusion"]}**',
            "",
            f'判定依据：{conclusion["key_finding"]}',
        ]
        if conclusion["missing_reference_terms"]:
            section_lines.append(
                f'未被正文引用的术语/缩略语：{", ".join(conclusion["missing_reference_terms"])}'
            )
        return "\n".join(section_lines)

    def _merge_report_with_conclusion(
        self,
        report_text: str,
        seed_data: Dict[str, Any],
        conclusion: Dict[str, Any],
    ) -> str:
        content = report_text.strip()
        prefix = ""
        if content.startswith("Final Answer:"):
            prefix = "Final Answer:\n"
            content = content[len("Final Answer:"):].lstrip()

        summary_section = self._build_summary_section(conclusion, seed_data)
        final_conclusion_section = self._build_final_conclusion_section(conclusion)

        lines = content.splitlines()
        if lines and lines[0].startswith("# "):
            merged_lines = [lines[0], "", summary_section]
            if len(lines) > 1:
                merged_lines.extend(["", *lines[1:]])
            merged_lines.extend(["", final_conclusion_section])
            return prefix + "\n".join(merged_lines)

        sections = [summary_section]
        if content:
            sections.extend([content, final_conclusion_section])
        else:
            sections.append(final_conclusion_section)
        return prefix + "\n\n".join(sections)

    def _build_supplemental_section(self, report_text: str, seed_data: Dict[str, Any], retrieval_rows: List[Dict[str, Any]]) -> str:
        missing_entries = []
        lower_report = report_text.lower()
        for entry in seed_data["entries"]:
            if self._normalize_term(entry["term"]) in lower_report:
                continue
            row = next((item for item in retrieval_rows if item["term"] == entry["term"]), None)
            evidence = row["evidence"] if row else []
            status = row["status"] if row else "错误"
            evidence_text = "<br>".join(
                [f'[{item["heading"]} / line {item["line"]}] {item["snippet"]}' for item in evidence[:4]]
            ) or "未在正文中检索到引用"
            missing_entries.append(
                {
                    "term": entry["term"],
                    "definition": entry["definition"] or "定义缺失",
                    "count": row["count"] if row else 0,
                    "status": status,
                    "evidence": evidence_text,
                }
            )

        if not missing_entries:
            return report_text

        supplemental_lines = [
            report_text.rstrip(),
            "",
            "## 规则兜底补录",
            "",
            "以下条目由规则解析器补录，用于覆盖 Markdown 表格错位或 LLM 漏提取的场景。",
            "",
            "| 序号 | 术语/缩略语 | 定义 | 出现次数 | 状态 | 详细引用证据 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for index, entry in enumerate(missing_entries, start=1):
            supplemental_lines.append(
                f'| {index} | {entry["term"]} | {entry["definition"]} | {entry["count"]} | {entry["status"]} | {entry["evidence"]} |'
            )
        return "\n".join(supplemental_lines)

    def _append_retrieval_appendix(self, report_text: str, retrieval_rows: List[Dict[str, Any]]) -> str:
        appendix_lines = [
            report_text.rstrip(),
            "",
            "## 程序化检索附录",
            "",
            "以下结果由程序化检索生成，用于稳定全文引用统计。",
            "",
            "- 英文/缩略语：分词检索",
            "- 中文术语：全文精确匹配",
            "- 证据片段：命中位置前后各10个字",
            "",
            "| 序号 | 术语/缩略语 | 检索方式 | 出现次数 | 状态 | 原文出处 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]

        for index, row in enumerate(retrieval_rows, start=1):
            evidence_text = "<br>".join(
                [
                    f'{evidence_index}. [{item["heading"]} / line {item["line"]}] {item["snippet"]}'
                    for evidence_index, item in enumerate(row["evidence"][:4], start=1)
                ]
            ) or "未检索到正文引用"
            appendix_lines.append(
                f'| {index} | {row["term"]} | {row["search_mode"]} | {row["count"]} | {row["status"]} | {evidence_text} |'
            )

        return "\n".join(appendix_lines)

    def _process_input_file(self, input_path: str) -> str:
        if input_path.lower().endswith(".md"):
            return input_path
        processor = ProcessDocumentTool()
        result = processor._run(input_path)
        if not result.lower().endswith(".md"):
            raise RuntimeError(result)
        return result

    def run(self, inputs: Dict[str, Any], queue: Queue, stop_event: Event) -> Any:
        input_path = self.get_primary_input_file(inputs).get("path")
        llm = LLMFactory.get_aliyun_llm()

        def step_callback(step_output):
            self._ensure_not_stopped(stop_event)
            data = {
                "type": "step",
                "content": str(step_output)
            }

            if hasattr(step_output, 'agent') and step_output.agent:
                if hasattr(step_output.agent, 'role'):
                    data["agent"] = step_output.agent.role
                    data["phase_id"] = self.PHASE_MAP.get(step_output.agent.role, 'unknown_phase')
                else:
                    data["agent"] = str(step_output.agent)
                    data["phase_id"] = self.PHASE_MAP.get(str(step_output.agent), 'unknown_phase')

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
                    output = output[:500] + "... (truncated)"
                data["tool_output"] = output

            queue.put(data)

        def task_callback(task_output):
            self._ensure_not_stopped(stop_event)
            try:
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

                phase_id = self.PHASE_MAP.get(agent_role, 'unknown_phase')

                queue.put({
                    "type": "task_completed",
                    "data": {
                        "phase_id": phase_id,
                        "agent": agent_role,
                        "description": description
                    }
                })
            except Exception as e:
                print(f"Error in task callback: {e}")

        self._ensure_not_stopped(stop_event)
        markdown_path = self._process_input_file(input_path)
        queue.put({
            "type": "step",
            "agent": "文档处理专家",
            "phase_id": "phase_1",
            "content": f"文档预处理完成: {markdown_path}",
            "thought": "已完成输入文件标准化，后续阶段直接基于 Markdown 分析。",
        })
        queue.put({
            "type": "task_completed",
            "data": {
                "phase_id": "phase_1",
                "agent": "文档处理专家",
                "description": f"已准备 Markdown 文件 {markdown_path}",
            }
        })

        seed_data = self._parse_seed_terms(markdown_path)
        seed_context = self._build_seed_context(seed_data)
        retrieval_rows = self._build_retrieval_audit(seed_data)
        retrieval_context = self._build_retrieval_context(retrieval_rows)
        conclusion = self._evaluate_audit_result(seed_data, retrieval_rows)
        queue.put({
            "type": "step",
            "agent": "术语提取员",
            "phase_id": "phase_2",
            "content": f"规则兜底抽取完成，共识别 {len(seed_data['entries'])} 项术语/缩略语。",
            "thought": seed_context,
        })
        queue.put({
            "type": "step",
            "agent": "术语审计员",
            "phase_id": "phase_3",
            "content": f"程序化检索基线已生成，共完成 {len(retrieval_rows)} 项全文引用统计。",
            "thought": retrieval_context,
        })

        roles = TermAuditRoles(llm=llm)
        tasks = TermAuditTasks()

        extractor = roles.term_extractor(callback=step_callback)
        auditor = roles.term_auditor(callback=step_callback)
        verifier = roles.term_verifier(callback=step_callback)
        reporter = roles.report_generator(callback=step_callback)

        task_extract_a = tasks.extract_terms_task_a(extractor, markdown_path, seed_context)
        task_extract_b = tasks.extract_terms_task_b(extractor, markdown_path, seed_context)
        task_merge = tasks.merge_terms_task(extractor, task_extract_a, task_extract_b, seed_context)
        task_audit = tasks.audit_terms_task(auditor, task_merge, markdown_path, seed_context, retrieval_context)
        task_verify = tasks.verify_zero_count_task(verifier, task_audit, markdown_path, retrieval_context)
        task_report = tasks.generate_report_task(reporter, task_extract_a, task_verify, retrieval_context)

        crew = Crew(
            agents=[extractor, auditor, verifier, reporter],
            tasks=[
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
        if isinstance(result, str):
            supplemented_result = self._build_supplemental_section(result, seed_data, retrieval_rows)
            merged_result = self._merge_report_with_conclusion(supplemented_result, seed_data, conclusion)
            final_result = self._append_retrieval_appendix(merged_result, retrieval_rows)
            queue.put({
                "type": "step",
                "agent": "报告生成员",
                "phase_id": "phase_5",
                "content": f'检查项最终结论：{conclusion["finding_conclusion"]}',
                "thought": conclusion["key_finding"],
            })
            return final_result
        return result

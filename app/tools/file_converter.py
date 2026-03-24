import json
import os
import re
from pdf2docx import Converter
from markitdown import MarkItDown

class FileConverter:
    def __init__(self, upload_dir: str, output_dir: str):
        self.upload_dir = upload_dir
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def pdf_to_docx(self, pdf_path: str) -> str:
        """Converts PDF to DOCX using pdf2docx."""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found at: {pdf_path}")
            
        filename = os.path.basename(pdf_path)
        name_without_ext = os.path.splitext(filename)[0]
        docx_path = os.path.join(self.output_dir, f"{name_without_ext}.docx")
        
        try:
            cv = Converter(pdf_path)
            cv.convert(docx_path)
            cv.close()
            return docx_path
        except Exception as e:
            raise RuntimeError(f"Failed to convert PDF to DOCX: {str(e)}")

    def docx_to_md(self, docx_path: str) -> str:
        """Converts DOCX to Markdown using MarkItDown."""
        # Ensure markitdown is used as requested
        filename = os.path.basename(docx_path)
        name_without_ext = os.path.splitext(filename)[0]
        md_path = os.path.join(self.output_dir, f"{name_without_ext}.md")
        
        try:
            md = MarkItDown()
            result = md.convert(docx_path)
            
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(result.text_content)
                
            return md_path
        except Exception as e:
            raise RuntimeError(f"Failed to convert DOCX to MD using MarkItDown: {str(e)}")

    def _page_json_path_from_md(self, md_path: str) -> str:
        base_path, _ = os.path.splitext(md_path)
        return f"{base_path}.pages.json"

    def _normalize_page_label(self, value: str) -> str | None:
        if not value:
            return None

        normalized_value = value.strip().replace("\\", "")
        normalized_value = re.sub(r"\s+", "", normalized_value)

        page_match = re.fullmatch(r"第([0-9IVXLCDMivxlcdm]+)页", normalized_value)
        if page_match:
            normalized_value = page_match.group(1)

        if re.fullmatch(r"\d{1,4}", normalized_value):
            return normalized_value

        roman_value = normalized_value.upper()
        if re.fullmatch(r"[IVXLCDM]{1,8}", roman_value):
            return roman_value

        return None

    def _is_page_marker_line(self, line: str) -> tuple[bool, str | None, int]:
        stripped_line = line.strip()
        if not stripped_line.startswith("|") or not stripped_line.endswith("|"):
            return False, None, 0

        cells = [cell.strip() for cell in stripped_line.split("|")[1:-1]]
        non_empty_cells = [cell for cell in cells if cell]
        if len(non_empty_cells) < 2:
            return False, None, 0

        exclusion_keywords = ("总页数", "文件编号", "发布日期", "文件名称", "版本记录", "审批记录")
        footer_keywords = (
            "©",
            "专属",
            "限制条件",
            "confidential",
            "copyright",
            "intellectual property",
            "all rights reserved",
            "知识产权",
            "版权所有",
        )

        best_label = None
        best_score = 0

        for cell_index, cell in enumerate(cells):
            page_label = self._normalize_page_label(cell)
            if not page_label:
                continue

            context_cells = [context_cell for index, context_cell in enumerate(cells) if index != cell_index and context_cell.strip()]
            context_text = " ".join(context_cells).lower()
            if any(keyword.lower() in context_text for keyword in exclusion_keywords):
                continue

            marker_score = 0

            if len(non_empty_cells) <= 3:
                marker_score += 1

            if any(keyword in context_text for keyword in footer_keywords):
                marker_score += 4

            if re.search(r"[A-Z]{2,}\d{2,}|[A-Z0-9]+-[A-Z0-9-]+", " ".join(context_cells)):
                marker_score += 2

            if len(context_text) >= 10:
                marker_score += 1

            if cell_index != len(cells) - 1:
                marker_score += 1

            if marker_score > best_score:
                best_label = page_label
                best_score = marker_score

        return best_score >= 4, best_label, best_score

    def generate_page_json_from_markdown(self, md_path: str) -> str:
        if not os.path.exists(md_path):
            raise FileNotFoundError(f"Markdown file not found at: {md_path}")

        with open(md_path, "r", encoding="utf-8") as file:
            raw_content = file.read()

        lines = raw_content.splitlines()
        pages = []
        buffer_lines = []
        buffer_start_line = 1

        for index, line in enumerate(lines, start=1):
            is_marker, page_label, marker_score = self._is_page_marker_line(line)
            if is_marker and page_label:
                page_content = "\n".join(buffer_lines).strip()
                if page_content:
                    pages.append(
                        {
                            "page_label": page_label,
                            "content_start_line": buffer_start_line,
                            "content_end_line": index - 1,
                            "marker_line": index,
                            "marker_score": marker_score,
                            "page_content": page_content,
                        }
                    )

                buffer_lines = []
                buffer_start_line = index + 1
                continue

            buffer_lines.append(line)

        trailing_content = "\n".join(buffer_lines).strip()
        page_json_path = self._page_json_path_from_md(md_path)

        payload = {
            "markdown_path": md_path,
            "page_json_path": page_json_path,
            "page_count": len(pages),
            "has_trailing_unassigned_content": bool(trailing_content),
            "pages": pages,
        }

        if trailing_content:
            payload["trailing_unassigned_content"] = {
                "content_start_line": buffer_start_line,
                "content_end_line": len(lines),
                "page_content": trailing_content,
            }

        with open(page_json_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

        return page_json_path

    def process_file(self, pdf_path: str) -> str:
        """Pipeline: PDF -> DOCX -> MD."""
        docx_path = self.pdf_to_docx(pdf_path)
        md_path = self.docx_to_md(docx_path)
        self.generate_page_json_from_markdown(md_path)
        return md_path

import os
import json
import re
from typing import Optional, Dict, Any, List
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

try:
    import fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


def build_header_footer_json_path(pdf_path: str) -> str:
    output_dir = os.path.join(os.getcwd(), "outputs")
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    return os.path.join(output_dir, f"{base_name}.header_footer.json")


class ExtractHeaderFooterInput(BaseModel):
    pdf_path: str = Field(description="The full path to the PDF file to be processed.")


class ReadHeaderFooterJsonInput(BaseModel):
    input_value: str = Field(description="PDF路径、JSON路径，或上一任务直接返回的JSON字符串")


class ExtractHeaderFooterJsonTool(BaseTool):
    name: str = "Extract Header Footer JSON"
    description: str = (
        "从 PDF 原文件逐页提取页眉、页脚、页码信息，生成 header_footer.json 文件。"
        "直接基于 PDF 逐页版面解析，不依赖 Word section。"
        "输出包含 baseline 基准信息、continuity_check 连续性检查。"
    )
    args_schema: type[BaseModel] = ExtractHeaderFooterInput

    def _run(self, pdf_path: str) -> str:
        if not PYMUPDF_AVAILABLE:
            return json.dumps({"error": "PyMuPDF (fitz) is not installed. Please install it with: pip install pymupdf"}, ensure_ascii=False)
        
        if not os.path.exists(pdf_path):
            return json.dumps({"error": f"PDF file not found: {pdf_path}"}, ensure_ascii=False)
        
        try:
            result = self._extract_header_footer(pdf_path)
            json_path = build_header_footer_json_path(pdf_path)
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            return json.dumps({
                "success": True,
                "header_footer_json_path": json_path,
                "source_pdf": pdf_path,
                "total_pages": result["total_pages"],
                "body_pages_count": result.get("body_pages_count", 0),
                "message": f"已成功提取页眉页脚信息，JSON文件保存在: {json_path}"
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Error extracting header/footer: {str(e)}"}, ensure_ascii=False)

    def _extract_header_footer(self, pdf_path: str) -> Dict[str, Any]:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        pages_data = []
        baseline = {
            "doc_no": "",
            "doc_version": "",
            "baseline_page_index": 0,
            "baseline_evidence": ""
        }
        
        all_page_labels = []
        body_page_labels = []
        body_pages_count = 0
        
        front_page_keywords = [
            '封面', '目录', '目次', '签署页', '版本记录', '修订记录',
            'contents', 'cover', 'revision history', '修订历史',
            '前言', 'foreword', '引言', 'introduction'
        ]
        
        for page_idx in range(total_pages):
            page = doc[page_idx]
            page_dict = page.get_text("dict")
            
            blocks = page_dict.get("blocks", [])
            text_lines = []
            all_page_text = []
            
            for block in blocks:
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        text = ""
                        for span in line.get("spans", []):
                            text += span.get("text", "")
                        bbox = line.get("bbox", [0, 0, 0, 0])
                        if text.strip():
                            text_lines.append({
                                "text": text.strip(),
                                "bbox": bbox,
                                "y0": bbox[1],
                                "y1": bbox[3]
                            })
                            all_page_text.append(text.strip())
            
            page_height = page_dict.get("height", 800)
            header_threshold = page_height * 0.15
            footer_threshold = page_height * 0.85
            
            header_candidates = [l for l in text_lines if l["y1"] <= header_threshold]
            footer_candidates = [l for l in text_lines if l["y0"] >= footer_threshold]
            
            header_text = " ".join([l["text"] for l in header_candidates])
            footer_text = " ".join([l["text"] for l in footer_candidates])
            
            header_evidence = self._get_evidence_text(header_candidates)
            footer_evidence = self._get_evidence_text(footer_candidates)
            
            page_label = None
            page_label_evidence = ""
            page_label_detected = False
            
            page_label, page_label_evidence = self._extract_page_label(footer_candidates + header_candidates)
            if page_label:
                page_label_detected = True
            
            contains_doc_no = self._check_doc_no(header_text + " " + footer_text)
            contains_doc_version = self._check_doc_version(header_text + " " + footer_text)
            contains_copyright = self._check_copyright(footer_text)
            
            full_page_text = " ".join(all_page_text)
            is_body_page = self._is_body_page(
                page_idx, total_pages, header_text, footer_text, 
                full_page_text, page_label, front_page_keywords
            )
            
            if is_body_page:
                body_pages_count += 1
            
            extraction_confidence = self._calculate_confidence(
                header_candidates, footer_candidates, page_label, is_body_page
            )
            
            needs_manual_review = extraction_confidence == "low"
            
            notes = ""
            if not header_candidates:
                notes = "未检测到页眉区域内容"
            elif not footer_candidates:
                notes = "未检测到页脚区域内容"
            
            page_data = {
                "physical_page_index": page_idx + 1,
                "logical_page_label": page_label,
                "is_body_page": is_body_page,
                "header_text": header_text,
                "footer_text": footer_text,
                "header_evidence": header_evidence,
                "footer_evidence": footer_evidence,
                "page_label_evidence": page_label_evidence,
                "contains_doc_no": contains_doc_no,
                "contains_doc_version": contains_doc_version,
                "contains_copyright": contains_copyright,
                "page_number_detected": page_label_detected,
                "extraction_confidence": extraction_confidence,
                "needs_manual_review": needs_manual_review,
                "notes": notes
            }
            
            pages_data.append(page_data)
            
            if page_label:
                all_page_labels.append({
                    "physical_page_index": page_idx + 1,
                    "logical_page_label": page_label,
                    "is_body_page": is_body_page
                })
                if is_body_page:
                    body_page_labels.append({
                        "physical_page_index": page_idx + 1,
                        "logical_page_label": page_label
                    })
            
            if page_idx == 0 or (not baseline["doc_no"] and contains_doc_no):
                doc_no = self._extract_doc_no(header_text + " " + footer_text)
                doc_version = self._extract_doc_version(header_text + " " + footer_text)
                
                if doc_no:
                    baseline["doc_no"] = doc_no
                    baseline["doc_version"] = doc_version
                    baseline["baseline_page_index"] = page_idx + 1
                    baseline["baseline_evidence"] = header_text if header_text else footer_text
        
        doc.close()
        
        continuity_check = self._check_continuity(body_page_labels)
        
        return {
            "source_pdf": pdf_path,
            "total_pages": total_pages,
            "body_pages_count": body_pages_count,
            "baseline": baseline,
            "pages": pages_data,
            "continuity_check": continuity_check
        }

    def _get_evidence_text(self, candidates: List[Dict]) -> str:
        if not candidates:
            return ""
        return " | ".join([c["text"] for c in candidates[:3]])

    def _extract_page_label(self, candidates: List[Dict]) -> tuple:
        patterns = [
            (r'[第\s]*(\d+)\s*[页\s]', 'arabic_page'),
            (r'[Pp]age\s*(\d+)', 'page_en'),
            (r'(\d+)\s*/\s*\d+', 'page_of'),
            (r'-\s*(\d+)\s*-', 'dash_page'),
            (r'^[IVXLC]+$', 'roman'),
            (r'^\d{1,3}$', 'simple_number'),
        ]
        
        for candidate in candidates:
            text = candidate["text"].strip()
            
            for pattern, pattern_type in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    if pattern_type == 'roman':
                        return self._roman_to_arabic(text), text
                    elif pattern_type in ['arabic_page', 'page_en', 'page_of', 'dash_page']:
                        return match.group(1), text
                    elif pattern_type == 'simple_number':
                        num = int(match.group(0))
                        if 1 <= num <= 999:
                            return str(num), text
        
        return None, ""

    def _roman_to_arabic(self, roman: str) -> str:
        roman = roman.upper().strip()
        values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        
        if not all(c in values for c in roman):
            return roman
        
        total = 0
        prev_value = 0
        for char in reversed(roman):
            value = values.get(char, 0)
            if value < prev_value:
                total -= value
            else:
                total += value
            prev_value = value
        
        return str(total)

    def _check_doc_no(self, text: str) -> bool:
        patterns = [
            r'[A-Z]{2,}[-\d]+',
            r'\d{2,}[-\d]+[-\d]+',
            r'文件编号',
            r'编号[：:\s]*[A-Z0-9-]+',
        ]
        for pattern in patterns:
            if re.search(pattern, text):
                return True
        return False

    def _check_doc_version(self, text: str) -> bool:
        patterns = [
            r'[Vv]\d+(\.\d+)?',
            r'版本[：:\s]*[A-Z0-9.]+',
            r'[Rr]ev\.?\s*\d+',
            r'第\s*\d+\s*版',
        ]
        for pattern in patterns:
            if re.search(pattern, text):
                return True
        return False

    def _check_copyright(self, text: str) -> bool:
        patterns = [
            r'版权所有',
            r'著作权',
            r'[Cc]opyright',
            r'©',
            r'\(C\)',
        ]
        for pattern in patterns:
            if re.search(pattern, text):
                return True
        return False

    def _extract_doc_no(self, text: str) -> str:
        patterns = [
            r'([A-Z]{2,}[-\d]+(?:-\d+)?)',
            r'(文件编号[：:\s]*[A-Z0-9-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    def _extract_doc_version(self, text: str) -> str:
        patterns = [
            r'([Vv]\d+(?:\.\d+)?)',
            r'(版本[：:\s]*[A-Z0-9.]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    def _is_body_page(self, page_idx: int, total_pages: int, 
                       header_text: str, footer_text: str,
                       full_page_text: str, page_label: Optional[str],
                       front_page_keywords: List[str]) -> bool:
        if page_idx == 0:
            return False
        return True

    def _calculate_confidence(self, header_candidates: List, footer_candidates: List,
                              page_label: Optional[str], is_body_page: bool) -> str:
        score = 0
        
        if header_candidates:
            score += 1
        if footer_candidates:
            score += 1
        if page_label:
            score += 2
        if is_body_page and page_label:
            score += 1
        
        if score >= 4:
            return "high"
        elif score >= 2:
            return "medium"
        else:
            return "low"

    def _check_continuity(self, body_page_labels: List[Dict]) -> Dict[str, Any]:
        if not body_page_labels:
            return {
                "checked_body_pages": [],
                "is_continuous": None,
                "issues": ["未检测到正文页码"]
            }
        
        checked_pages = [p["physical_page_index"] for p in body_page_labels]
        labels = []
        
        for p in body_page_labels:
            label = p["logical_page_label"]
            try:
                labels.append(int(label))
            except (ValueError, TypeError):
                labels.append(None)
        
        valid_labels = [l for l in labels if l is not None]
        
        if not valid_labels:
            return {
                "checked_body_pages": checked_pages,
                "is_continuous": None,
                "issues": ["无法识别有效的正文页码"]
            }
        
        issues = []
        sorted_labels = sorted(valid_labels)
        
        for i in range(1, len(sorted_labels)):
            prev = sorted_labels[i-1]
            curr = sorted_labels[i]
            if curr - prev > 1:
                issues.append(f"页码跳页: {prev} -> {curr}")
            elif curr == prev:
                issues.append(f"页码重复: {prev}")
            elif curr < prev:
                issues.append(f"页码倒序: {prev} -> {curr}")
        
        is_continuous = len(issues) == 0
        
        return {
            "checked_body_pages": checked_pages,
            "is_continuous": is_continuous,
            "issues": issues if issues else ["页码连续"]
        }


class ReadHeaderFooterJsonTool(BaseTool):
    name: str = "Read Header Footer JSON"
    description: str = (
        "读取 header_footer.json，支持 PDF 路径、JSON 路径或 JSON 字符串。"
        "输入可以是：1) PDF 文件路径；2) JSON 文件路径；3) 上一任务返回的 JSON 字符串。"
    )
    args_schema: type[BaseModel] = ReadHeaderFooterJsonInput

    def _run(self, input_value: str) -> str:
        try:
            text = input_value.strip()
            
            if text.startswith("{") and text.endswith("}"):
                try:
                    data = json.loads(text)
                    if "header_footer_json_path" in data:
                        json_path = data["header_footer_json_path"]
                        if os.path.isabs(json_path) and os.path.exists(json_path):
                            with open(json_path, "r", encoding="utf-8") as f:
                                file_data = json.load(f)
                            return json.dumps({
                                "success": True,
                                "header_footer_json_path": json_path,
                                "data": file_data,
                                "source": "json_string_with_path"
                            }, ensure_ascii=False, indent=2)
                    
                    if "data" in data:
                        return json.dumps({
                            "success": True,
                            "data": data["data"],
                            "source": "raw_json_with_data"
                        }, ensure_ascii=False, indent=2)
                    
                    return json.dumps({
                        "success": True,
                        "data": data,
                        "source": "raw_json"
                    }, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            
            if text.lower().endswith(".pdf"):
                json_path = build_header_footer_json_path(text)
            else:
                json_path = text
            
            if not os.path.isabs(json_path):
                possible_paths = [
                    os.path.join(os.getcwd(), json_path),
                    os.path.join(os.getcwd(), "outputs", os.path.basename(json_path)),
                ]
                
                for path in possible_paths:
                    if os.path.exists(path):
                        json_path = path
                        break
            
            if not os.path.exists(json_path):
                outputs_dir = os.path.join(os.getcwd(), "outputs")
                if os.path.exists(outputs_dir):
                    json_files = [f for f in os.listdir(outputs_dir) if f.endswith(".header_footer.json")]
                    if json_files:
                        json_path = os.path.join(outputs_dir, json_files[0])
            
            if not os.path.exists(json_path):
                return json.dumps({
                    "success": False,
                    "error": f"Header footer JSON file not found: {json_path}",
                    "hint": "请确保先调用 Extract Header Footer JSON 工具生成 JSON 文件",
                    "cwd": os.getcwd(),
                    "outputs_dir": os.path.join(os.getcwd(), "outputs")
                }, ensure_ascii=False)
            
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            return json.dumps({
                "success": True,
                "header_footer_json_path": json_path,
                "data": data,
                "source": "file"
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "cwd": os.getcwd()
            }, ensure_ascii=False)

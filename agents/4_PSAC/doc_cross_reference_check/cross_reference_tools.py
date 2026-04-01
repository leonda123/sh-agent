import json
import os
import re
from typing import Dict, List, Any, Optional
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from app.tools.file_converter import FileConverter


class ProcessDocumentInput(BaseModel):
    pdf_path: str = Field(description="待处理的 PDF 文件完整路径")


class ProcessDocumentTool(BaseTool):
    name: str = "Process Document"
    description: str = (
        "将 PDF 转换为 Markdown 格式，处理链路为 PDF → DOCX → Markdown，"
        "同时生成页码映射文件 pages.json。返回 Markdown 文件路径。"
    )
    args_schema: type[BaseModel] = ProcessDocumentInput

    def _run(self, pdf_path: str) -> str:
        output_dir = os.path.join(os.getcwd(), "outputs")
        converter = FileConverter(os.path.dirname(pdf_path), output_dir)
        try:
            md_path = converter.process_file(pdf_path)
            return md_path
        except Exception as e:
            return f"Error processing document: {str(e)}"


class ReadFileInput(BaseModel):
    file_path: str = Field(description="待读取文件的完整路径")


class ReadFileTool(BaseTool):
    name: str = "Read File"
    description: str = "读取文件全部文本内容"
    args_schema: type[BaseModel] = ReadFileInput

    def _run(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                return content
        except Exception as e:
            return f"Error reading file: {str(e)}"


class ReadPagesInput(BaseModel):
    md_path: str = Field(description="Markdown 文件路径")


class ReadPagesTool(BaseTool):
    name: str = "Read Pages"
    description: str = (
        "读取 Markdown 文件对应的 pages.json 文件，返回每页的结构化数据。"
        "只需传入 Markdown 文件路径，工具会自动定位 pages.json 文件。"
    )
    args_schema: type[BaseModel] = ReadPagesInput

    def _run(self, md_path: str) -> str:
        try:
            pages_json_path = None
            
            if md_path.endswith(".pages.json"):
                pages_json_path = md_path
            elif md_path.endswith(".md"):
                pages_json_path = md_path[:-3] + ".pages.json"
            else:
                pages_json_path = md_path + ".pages.json"
            
            if not os.path.exists(pages_json_path):
                test_path = md_path.replace(".md", ".pages.json")
                if os.path.exists(test_path):
                    pages_json_path = test_path
                else:
                    return json.dumps(
                        {"error": f"未找到 pages.json 文件: {pages_json_path}", "success": False},
                        ensure_ascii=False,
                    )

            with open(pages_json_path, "r", encoding="utf-8") as f:
                pages_data = json.load(f)

            pages = pages_data.get("pages", [])
            
            if not pages:
                return json.dumps(
                    {"error": "pages.json 中没有页面数据", "success": False},
                    ensure_ascii=False,
                )
            
            result = {
                "total_pages": len(pages),
                "pages": []
            }
            
            for page_info in pages:
                page_label = page_info.get("page_label", "")
                page_content = page_info.get("page_content", "")
                
                result["pages"].append({
                    "page_label": page_label,
                    "content": page_content,
                })

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps(
                {"error": f"读取页面数据失败: {str(e)}", "success": False},
                ensure_ascii=False,
            )


class FullTextSearchInput(BaseModel):
    md_path: str = Field(description="Markdown 文件路径")
    search_term: str = Field(default="错误!未找到引用源。", description="要搜索的文本内容")


class FullTextSearchTool(BaseTool):
    name: str = "Full Text Search"
    description: str = (
        "在 Markdown 文件全文中精确搜索指定文本，返回命中次数、命中位置和原文片段。"
        "默认搜索'错误!未找到引用源。'"
    )
    args_schema: type[BaseModel] = FullTextSearchInput

    def _run(self, md_path: str, search_term: str = "错误!未找到引用源。") -> str:
        try:
            if not os.path.exists(md_path):
                return json.dumps(
                    {"error": f"文件不存在: {md_path}", "success": False},
                    ensure_ascii=False,
                )
            
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if not content:
                return json.dumps(
                    {"error": "文件内容为空", "success": False},
                    ensure_ascii=False,
                )
            
            hits = []
            start = 0
            while True:
                pos = content.find(search_term, start)
                if pos == -1:
                    break
                
                context_start = max(0, pos - 50)
                context_end = min(len(content), pos + len(search_term) + 50)
                context = content[context_start:context_end]
                
                hits.append({
                    "position": pos,
                    "context": context
                })
                
                start = pos + len(search_term)
            
            result = {
                "success": True,
                "search_term": search_term,
                "hit_count": len(hits),
                "hits": hits
            }
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            return json.dumps(
                {"error": f"全文检索失败: {str(e)}", "success": False},
                ensure_ascii=False,
            )


class PageByPageSearchInput(BaseModel):
    md_path: str = Field(description="Markdown 文件路径")
    search_term: str = Field(default="错误!未找到引用源。", description="要搜索的文本内容")


class PageByPageSearchTool(BaseTool):
    name: str = "Page By Page Search"
    description: str = (
        "逐页搜索指定文本，返回每页的命中次数、命中页码和原文片段。"
        "需要配合 pages.json 文件使用。默认搜索'错误!未找到引用源。'"
    )
    args_schema: type[BaseModel] = PageByPageSearchInput

    def _run(self, md_path: str, search_term: str = "错误!未找到引用源。") -> str:
        try:
            pages_json_path = None
            
            if md_path.endswith(".pages.json"):
                pages_json_path = md_path
            elif md_path.endswith(".md"):
                pages_json_path = md_path[:-3] + ".pages.json"
            else:
                pages_json_path = md_path + ".pages.json"
            
            if not os.path.exists(pages_json_path):
                test_path = md_path.replace(".md", ".pages.json")
                if os.path.exists(test_path):
                    pages_json_path = test_path
                else:
                    return json.dumps(
                        {"error": f"未找到 pages.json 文件: {pages_json_path}", "success": False},
                        ensure_ascii=False,
                    )
            
            with open(pages_json_path, "r", encoding="utf-8") as f:
                pages_data = json.load(f)
            
            pages = pages_data.get("pages", [])
            
            if not pages:
                return json.dumps(
                    {"error": "pages.json 中没有页面数据", "success": False},
                    ensure_ascii=False,
                )
            
            total_hits = 0
            page_hits = []
            
            for page_info in pages:
                page_label = page_info.get("page_label", "")
                page_content = page_info.get("page_content", "")
                
                if not page_content:
                    continue
                
                hits_in_page = []
                start = 0
                while True:
                    pos = page_content.find(search_term, start)
                    if pos == -1:
                        break
                    
                    context_start = max(0, pos - 50)
                    context_end = min(len(page_content), pos + len(search_term) + 50)
                    context = page_content[context_start:context_end]
                    
                    hits_in_page.append({
                        "position": pos,
                        "context": context
                    })
                    
                    start = pos + len(search_term)
                
                if hits_in_page:
                    total_hits += len(hits_in_page)
                    page_hits.append({
                        "page_label": page_label,
                        "hit_count": len(hits_in_page),
                        "hits": hits_in_page
                    })
            
            result = {
                "success": True,
                "search_term": search_term,
                "total_hit_count": total_hits,
                "hit_page_count": len(page_hits),
                "page_hits": page_hits
            }
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            return json.dumps(
                {"error": f"逐页检索失败: {str(e)}", "success": False},
                ensure_ascii=False,
            )

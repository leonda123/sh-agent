import os
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

    def process_file(self, pdf_path: str) -> str:
        """Pipeline: PDF -> DOCX -> MD."""
        docx_path = self.pdf_to_docx(pdf_path)
        md_path = self.docx_to_md(docx_path)
        return md_path

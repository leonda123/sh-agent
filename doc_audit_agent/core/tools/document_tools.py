from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from doc_audit_agent.core.tools.file_converter import FileConverter
import os

class ProcessDocumentInput(BaseModel):
    pdf_path: str = Field(description="The full path to the PDF file to be processed.")

class ProcessDocumentTool(BaseTool):
    name: str = "Process Document"
    description: str = (
        "Converts a PDF file to Markdown format for easier analysis. "
        "It first converts PDF to Word (docx) and then to Markdown (md) to preserve formatting."
    )
    args_schema: type[BaseModel] = ProcessDocumentInput
    
    def _run(self, pdf_path: str) -> str:
        """Process the PDF file and return the path to the Markdown file."""
        # Assuming output directory is relative to the project root or configured
        output_dir = os.path.join(os.getcwd(), "doc_audit_agent", "outputs")
        converter = FileConverter(os.path.dirname(pdf_path), output_dir)
        try:
            md_path = converter.process_file(pdf_path)
            return f"Successfully converted {pdf_path} to {md_path}. You can now read this file."
        except Exception as e:
            return f"Error processing document: {str(e)}"

class ReadFileTool(BaseTool):
    name: str = "Read File"
    description: str = "Reads the content of a file."

    def _run(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                # If content is extremely large, warn the agent, but return full content as requested by agent logic.
                # However, for console logs, we rely on the framework or callback truncation.
                # Here we just return the content.
                return content
        except Exception as e:
            return f"Error reading file: {str(e)}"

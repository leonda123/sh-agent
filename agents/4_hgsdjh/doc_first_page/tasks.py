class FirstPageAuditTasks:
    def parse_document_task(self, input_path: str) -> str:
        return (
            "【阶段一：解析】"
            f" 接收输入文件 {input_path}，将 PDF 预处理为 Markdown，并稳定定位首页内容。"
        )

    def extract_fields_task(self) -> str:
        return (
            "【阶段二：提取】"
            " 从首页中检查文件名称、文件编号、版本、文件发布日期与版权声明，输出结构化结果。"
        )

    def summarize_task(self) -> str:
        return (
            "【阶段三：总结】"
            " 根据结构化检查结果生成 Markdown 报告，并明确给出“通过/不通过”结论。"
        )

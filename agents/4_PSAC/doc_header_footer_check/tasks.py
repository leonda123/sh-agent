from crewai import Task


class HeaderFooterTasks:
    def parse_document_task(self, agent, pdf_path):
        return Task(
            description=f"""
            【阶段一：文档解析】
            1. 接收文件：获取位于 {pdf_path} 的 PDF 文件。
            2. 页眉页脚提取：使用 `Extract Header Footer JSON` 工具直接从 PDF 原文件逐页提取页眉、页脚、页码信息。
            3. 工具返回：工具会返回一个 JSON 字符串，包含：
               - success: 是否成功
               - header_footer_json_path: 生成的 JSON 文件的绝对路径
               - source_pdf: 源 PDF 路径
               - total_pages: 总页数
               - message: 处理消息
            4. 输出要求：将工具返回的 JSON 中的 header_footer_json_path 作为你的最终回答。
            
            **关键指令**：
            - 调用 `Extract Header Footer JSON` 工具一次即可。
            - 工具返回的是 JSON 字符串，你需要从中提取 header_footer_json_path 字段。
            - 将该路径作为你的最终回答（Final Answer）。
            - **严禁**重复调用工具或进行任何额外的文本处理。
            """,
            expected_output="生成的 header_footer.json 文件的精确绝对路径。",
            agent=agent,
            max_retries=2
        )

    def extract_baseline_task(self, agent, parse_task):
        return Task(
            description="""
            【阶段二：基准信息提取】
            1. 获取 JSON 路径：从上一任务的输出中获取 header_footer.json 文件的绝对路径。
            2. 读取数据：使用 `Read Header Footer JSON` 工具读取该 JSON 文件。
               - 工具输入必须是上一任务返回的路径，**禁止使用占位符路径**。
            3. 提取基准：从 JSON 中的 `baseline` 字段提取首页基准信息：
               - doc_no：文件编号
               - doc_version：文件版本
               - baseline_page_index：基准所在页码
               - baseline_evidence：原文证据
            4. 验证完整性：确认基准信息是否完整，若缺失需明确说明。
            5. 输出结构：
               ```
               基准信息提取结果：
               - 文件编号：[值]
               - 文件版本：[值]
               - 基准页码：[值]
               - 原文证据：[值]
               - 完整性状态：[完整/缺失]
               ```
            
            **关键指令**：
            - 必须使用 `Read Header Footer JSON` 工具读取数据。
            - 工具输入必须是上一任务返回的真实路径。
            - 基准信息作为后续一致性校验的标准。
            - 最终结果必须放在 `Final Answer:` 之后。
            """,
            expected_output="包含文件编号、文件版本、基准页码、原文证据的结构化基准信息。",
            agent=agent,
            context=[parse_task],
            max_retries=2
        )

    def identify_header_footer_task(self, agent, parse_task):
        return Task(
            description="""
            【阶段三：页眉页脚识别】
            1. 获取 JSON 路径：从阶段一任务的输出中获取 header_footer.json 文件的绝对路径。
            2. 读取数据：使用 `Read Header Footer JSON` 工具读取该 JSON 文件。
               - 工具输入必须是阶段一任务返回的路径，**禁止使用占位符路径**。
            3. 统计所有页面（除首页外）：
               - 统计各页页眉内容
               - 统计各页页脚内容
               - 统计页码识别情况
            4. 输出结构：
               ```
               页眉页脚识别结果：
               - 总页数：[总数]
               - 检查页数：[总数-1，排除首页]
               - 页眉内容汇总：[去重后的页眉内容列表]
               - 页脚内容汇总：[去重后的页脚内容列表]
               - 页码识别情况：[已识别页码列表]
               - 连续性检查结果：[continuous/issues]
               ```
            
            **关键指令**：
            - 必须使用 `Read Header Footer JSON` 工具读取数据。
            - 工具输入必须是阶段一任务返回的真实路径。
            - **提取所有页面（除首页外），不再区分正文和非正文页**。
            - 最终结果必须放在 `Final Answer:` 之后。
            """,
            expected_output="包含总页数、页眉页脚汇总、页码识别情况的结构化识别结果。",
            agent=agent,
            context=[parse_task],
            max_retries=2
        )

    def a_round_check_task(self, agent, baseline_task, identify_task):
        return Task(
            description="""
            【阶段四：A轮核验】
            1. 获取 JSON 路径：从阶段一任务的输出中获取 header_footer.json 文件的绝对路径。
            2. 读取数据：使用 `Read Header Footer JSON` 工具读取该 JSON 文件。
               - 工具输入必须是阶段一任务返回的路径，**禁止使用占位符路径**。
            3. 逐页检查所有页面（除首页外）：
               - 检查项1：页眉是否包含文件编号和文件版本（检查 contains_doc_no 和 contains_doc_version）
               - 检查项2：页脚是否包含"版权所有"信息（检查 contains_copyright）
               - 检查项3：页脚是否包含页码（检查 page_number_detected）
            4. 输出格式：
               ```
               A轮核验报告：
               
               ## 逐页检查结果
               | 物理页码 | 逻辑页码 | 页眉完整性 | 页脚完整性 | 版权信息 | 页码存在 | 原文证据 |
               |---------|---------|-----------|-----------|---------|---------|---------|
               | [值] | [值] | [完整/缺失] | [完整/缺失] | [有/无] | [有/无] | [原文] |
               
               ## 汇总结果
               - 检查项1通过率：[通过页数/总检查页数]
               - 检查项2通过率：[通过页数/总检查页数]
               - 检查项3通过率：[通过页数/总检查页数]
               - 总体判定：[通过/不通过]
               ```
            
            **关键指令**：
            - 必须使用 `Read Header Footer JSON` 工具读取数据。
            - 工具输入必须是阶段一任务返回的真实路径。
            - **检查所有页面（除首页外），不再区分正文和非正文页**。
            - 每项判断必须给出原文证据（使用 header_evidence 和 footer_evidence）。
            - 对识别不清的页面，标记为"证据不足/需人工复核"。
            - 最终结果必须放在 `Final Answer:` 之后。
            """,
            expected_output="包含逐页检查结果表格和汇总通过率的A轮核验报告。",
            agent=agent,
            context=[baseline_task, identify_task],
            max_retries=3
        )

    def b_round_check_task(self, agent, baseline_task, identify_task):
        return Task(
            description="""
            【阶段五：B轮核验】
            作为独立的复核者，请**独立**执行以下步骤（不要参考A轮结果）：
            1. 获取 JSON 路径：从阶段一任务的输出中获取 header_footer.json 文件的绝对路径。
            2. 读取数据：使用 `Read Header Footer JSON` 工具读取该 JSON 文件。
               - 工具输入必须是阶段一任务返回的路径，**禁止使用占位符路径**。
            3. 一致性核验（检查所有页面，除首页外）：
               - 用首页基准的文件编号、文件版本反向核验各页页眉是否一致
               - 用 continuity_check 结果核验页码是否连续
               - 对"版权所有"信息表述进行复核
            4. 输出格式：
               ```
               B轮核验报告：
               
               ## 一致性检查结果
               | 物理页码 | 逻辑页码 | 页眉一致性 | 页码连续性 | 版权表述 | 差异描述 |
               |---------|---------|-----------|-----------|---------|---------|
               | [值] | [值] | [一致/不一致] | [连续/不连续] | [一致/不一致] | [描述] |
               
               ## 汇总结果
               - 页眉一致性：[一致/不一致]
               - 页码连续性：[连续/不连续]
               - 版权表述一致性：[一致/不一致]
               - 异常页清单：[页码列表]
               - 总体判定：[通过/不通过]
               ```
            
            **关键指令**：
            - 必须独立执行核验，不得参考A轮结果。
            - 必须使用 `Read Header Footer JSON` 工具读取数据。
            - 工具输入必须是阶段一任务返回的真实路径。
            - **检查所有页面（除首页外），不再区分正文和非正文页**。
            - 页眉一致性以首页基准（baseline）为标准。
            - 页码连续性以 continuity_check 为依据。
            - 最终结果必须放在 `Final Answer:` 之后。
            """,
            expected_output="包含一致性检查结果表格和异常页清单的B轮核验报告。",
            agent=agent,
            context=[baseline_task, identify_task],
            max_retries=3
        )

    def cross_validate_task(self, agent, a_round_task, b_round_task, baseline_task, identify_task):
        return Task(
            description="""
            【阶段六：交叉验证】
            你收到了A轮和B轮两份独立的核验报告，以及基准信息和识别结果。
            1. 数据比对：
               - 全面比对 A 轮和 B 轮报告中的所有检查项结果
            2. 针对性验证：
               - 如果两份报告完全一致 -> 直接标记为"已验证"
               - 如果发现不一致 -> 使用 `Read Header Footer JSON` 工具回到原文复核
                 * 工具输入必须是阶段一任务返回的真实路径
            3. 重点排除误判：
               - 将正文首行误识别为页眉
               - 将正文末行误识别为页脚
               - 将物理页序误判为正文页码
               - 因扫描裁切导致的页眉页脚缺失误判
            4. 输出格式：
               ```
               交叉验证报告：
               
               ## AB轮对比结果
               - AB轮交叉验证状态：[完全一致/存在分歧但已通过原文核定/仍有存疑]
               - 分歧项清单：[如有分歧，列出具体项]
               
               ## 最终判定
               - 业务逻辑1判定：[是/否]（页眉是否包含文件编号和文件版本）
                 * 依据：[原文证据]
               - 业务逻辑2判定：[是/否]（页眉是否与首页一致）
                 * 依据：[原文证据]
               - 业务逻辑3判定：[是/否]（页脚是否包含版权和页码且连续）
                 * 依据：[原文证据]
               
               ## 最终异常页清单
               | 页码 | 异常类型 | 异常描述 | 原文证据 |
               |-----|---------|---------|---------|
               | [值] | [类型] | [描述] | [证据] |
               
               ## 总体结论
               [通过/不通过]
               ```
            
            **关键指令**：
            - 当且仅当发现不一致时，才调用 `Read Header Footer JSON` 工具复核。
            - 工具输入必须是阶段一任务返回的真实路径，**禁止使用占位符路径**。
            - 不得因A/B轮分歧直接判定文档错误，必须以原文证据为准。
            - 最终结果必须放在 `Final Answer:` 之后。
            """,
            expected_output="包含AB轮对比结果、最终判定、异常页清单和总体结论的交叉验证报告。",
            agent=agent,
            context=[a_round_task, b_round_task, baseline_task, identify_task],
            max_retries=3
        )

    def generate_report_task(self, agent, cross_validate_task):
        return Task(
            description="""
            【阶段七：结果生成】
            基于交叉验证结果，生成专业级的页眉页脚完整性审查报告。
            
            **重要**：你必须输出完整的、格式化的 Markdown 报告，不能只输出"通过"或"不通过"。
            
            报告必须严格遵循以下完整格式：
            
            ```markdown
            # 页眉页脚完整性审查报告
            
            ## 1. 审查综述
            | 项目 | 详情 |
            | :--- | :--- |
            | 文档名称 | [从 source_pdf 提取文件名] |
            | 审查日期 | [当前日期，格式：YYYY-MM-DD] |
            | 审查结果 | **[通过/不通过]** |
            | 关键发现 | [一句话概括核心问题或"页眉页脚内容完整正确"] |
            
            ## 2. 检查项结论
            | 检查项 | 结论 | 依据 |
            | :--- | :--- | :--- |
            | 页眉是否包含文件编号和文件版本 | [是/否] | [具体的原文证据，引用 header_evidence] |
            | 页眉是否与首页一致 | [是/否] | [具体的原文证据，引用 baseline_evidence] |
            | 页脚是否包含版权信息和页码且连续 | [是/否] | [具体的原文证据，引用 footer_evidence 和 continuity_check] |
            
            ## 3. 基准信息
            - 文件编号：[从 baseline.doc_no 提取]
            - 文件版本：[从 baseline.doc_version 提取]
            - 基准页码：[从 baseline.baseline_page_index 提取]
            - 原文证据：[从 baseline.baseline_evidence 提取]
            
            ## 4. 页面检查详情
            | 物理页码 | 逻辑页码 | 页眉状态 | 页脚状态 | 版权信息 | 页码状态 | 备注 |
            | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
            | [逐页填写所有页面（除首页外）] |
            
            ## 5. 异常页清单
            [如有异常页，按以下格式列出]
            | 页码 | 异常类型 | 异常描述 | 原文证据 |
            | :--- | :--- | :--- | :--- |
            | [值] | [类型] | [描述] | [证据] |
            
            [如无异常页，填写"无异常页"]
            
            ## 6. 最终结语
            依据 AVICAS-312-100-T001《软件合格审定计划模板》要求，上传的软件合格审定计划中的页眉页脚内容[完整正确/存在以下问题：具体问题描述]。
            
            **审查结论**：[通过/不通过]
            ```
            
            **关键指令**：
            - **必须输出完整的 Markdown 格式报告**，不能只输出结论。
            - 报告必须包含所有 6 个章节。
            - 每项判断必须给出具体的原文证据。
            - 表格必须完整填写，不能留空。
            - **检查所有页面（除首页外），不再区分正文和非正文页**。
            - 最终结果必须放在 `Final Answer:` 之后。
            """,
            expected_output="完整的 Markdown 格式审查报告，包含审查综述、检查项结论、基准信息、页面检查详情、异常页清单和最终结语。",
            agent=agent,
            context=[cross_validate_task],
            max_retries=2
        )

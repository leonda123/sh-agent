from crewai import Task

class DocHistoryTasks:
    def process_document_task(self, agent, pdf_path):
        return Task(
            description=f"""
            【阶段一：文档解析】
            1. 接收文件：获取位于 {pdf_path} 的 PDF 文件。
            2. 格式转换：使用 Process Document 工具将其转换为机器可读的 Markdown 格式。
            3. 路径输出：确保输出转换后的 Markdown 文件绝对路径。
            
            **关键指令**：
            - 调用 `Process Document` 工具一次即可。
            - 一旦工具返回了文件路径（以 .md 结尾），**立即停止**工具调用。
            - 将该 Markdown 路径作为你的最终回答（Final Answer）。
            - **严禁**重复调用工具。
            """,
            expected_output="转换后的 Markdown 文件的精确绝对路径，不做任何修改。",
            agent=agent,
            max_retries=2
        )

    def analyze_content_task(self, agent, process_task):
        return Task(
            description="""
            【阶段二：内容提取 (A轮)】
            1. [读取数据]：读取上一步生成的 Markdown 文件。使用 `Read File` 工具。注意：只需关注前几页的内容（文档开头部分）即可找到“版本记录”、“更改描述”等章节。
            2. [版本记录扫描]：在文档前几页中找到“版本记录”、“历史版本”、“修订历史”等表格或章节。
            3. [信息提取]：
               - 记录所有的历史版本条目（版本号、发布日期/日期/更改日期、更改描述/变更描述/描述/变更号、作者/更改者等字段）。
               - 提取文档首页或封面的当前版本号信息。
               - 提取文档首页或封面的更改单据/单据号信息。
            4. [数据输出]：生成一份结构化提取清单，包含：
               - 提取到的所有版本历史记录明细（必须保留原文证据）
               - 首页提及的版本号与单据号
               - 每条记录是否包含必备字段（日期、描述、作者、版本）

            **关键指令**：
            - 你必须使用 `Read File` 工具读取 Markdown。
            - 最终结果必须放在 `Final Answer:` 之后。
            - 提取的内容要详实，保留上下文。
            """,
            expected_output="包含所有提取到的版本记录和首页版本信息的结构化报告，含原文证据。",
            agent=agent,
            context=[process_task],
            max_retries=3
        )

    def analyze_content_task_b(self, agent, process_task):
        return Task(
            description="""
            【阶段二：内容提取 (B轮)】
            作为独立的复核者，请**独立**执行以下步骤（不要参考A轮结果）：
            1. [读取数据]：重新读取 Markdown 文件。使用 `Read File` 工具。
            2. [独立扫描]：重新在文档前几页扫描版本记录。
            3. [独立提取]：重新提取所有历史版本条目及对应字段，以及首页的版本号和单据号。
            4. [数据输出]：生成你的独立结构化清单。

            **关键指令**：
            - 独立思考，提取记录和原文字段。
            - 最终报告必须放在 `Final Answer:` 之后。
            """,
            expected_output="一份独立的、包含版本记录信息的结构化提取报告。",
            agent=agent,
            context=[process_task],
            max_retries=3
        )

    def verify_analysis_task(self, agent, analyze_task_a, analyze_task_b, process_task):
        return Task(
            description="""
            【阶段三：交叉验证】
            你收到了两份独立的提取报告（A轮和B轮）。
            1. [数据比对]：
               - 全面比对 A 轮和 B 轮报告中的历史版本记录、字段信息以及首页版本信息。
            2. [针对性验证]：
               - 如果两份报告的数据完全一致 -> 直接标记为“完全一致”。
               - **如果发现不一致** -> 必须调用 `Read File` 工具重新读取 Markdown 原文中有争议的部分，以此判断哪一份报告是正确的。
            3. [最终合并]：
               - 生成一份**唯一的、合并后的**历史版本记录与首页信息清单。
               - 必须注明“AB轮交叉验证状态”。
            
            **关键指令**：
            - 最终输出必须以 `Final Answer:` 开头，后跟合并后的数据清单。
            """,
            expected_output="一份经过双重验证、包含 AB轮交叉验证状态的最终结构化版本记录数据清单。",
            agent=agent,
            context=[analyze_task_a, analyze_task_b, process_task],
            max_retries=3
        )

    def review_and_report_task(self, agent, verify_task):
        return Task(
            description="""
            【阶段四：结论生成】
            基于**阶段三验证后**的数据，按照审查规则进行最终判定，并生成 Markdown 报告。
            
            【审查规则】
            1. 正常初始版本，至少有一条历史版本记录。
            2. 如果有多条记录，需查看更改描述中是否有“发布日期/日期/更改日期”、“更改描述/变更描述/描述/变更号”、“作者/更改者”、“版本”等信息，以证明是否正确列出历史版本及其作者。
            3. 最后一行的版本（即最新版本）应该为当前版本，并检查首页是否提及该版本。
            4. 如果有多条版本记录，是否正确列出了历史版本的变更单据信息（变更号/单据号等）。
            
            报告格式必须如下：
            
            # 历史版本完整性审查报告

            ## 1. 检查规则及结果
            | 检查项 | 结果 (符合/不符合/不适用) | 备注/证据 |
            | :--- | :--- | :--- |
            | 存在版本记录 | | |
            | 记录字段完整(含日期,作者,描述,版本) | | |
            | 最新版本与首页一致 | | |
            | 列出变更单据信息 | | |

            ## 2. 详细证据
            列出提取到的各条版本记录及首页信息证据。

            ## 3. 最终结论
            **[通过/不通过]**
            （如果不通过，请简述原因。如缺少记录、字段不全、版本不一致等）
            """,
            expected_output="一份符合要求的最终 Markdown 审计报告，包含明确的 [通过/不通过] 结论。",
            agent=agent,
            context=[verify_task],
            max_retries=2
        )

from crewai import Task
import os

class ReferenceFileTasks:
    def parse_document_task(self, agent, pdf_path):
        return Task(
            description=f"""
            【阶段一：文档解析】
            1. 接收文件：获取位于 {pdf_path} 的PDF文件。
            2. 格式转换：使用文档处理工具将其转换为机器可读的Markdown格式。
            3. 辅助产物：该工具会同时生成一个与Markdown同名的页码映射文件，命名规则为`同名.pages.json`。
               例如：如果输出是`xxx.md`，则辅助页码文件为`xxx.pages.json`。
            4. 路径输出：确保输出转换后的Markdown文件绝对路径，不要对文件名中的空格或字符进行任何修改。
            
            **关键指令**：
            - 调用`Process Document`工具一次即可。
            - 一旦工具返回了文件路径（以.md结尾），**立即停止**工具调用。
            - 将该Markdown路径作为你的最终回答（Final Answer）。
            - **严禁**重复调用工具或进行任何额外的文本处理。
            """,
            expected_output="转换后的Markdown文件的精确绝对路径，不做任何修改。",
            agent=agent,
            max_retries=2
        )

    def extract_reference_files_task(self, agent, parse_task):
        return Task(
            description="""
            【阶段二：引用文件提取】
            1. [读取数据]：读取上一个任务生成的Markdown文件。注意：必须使用上一步输出的精确路径，不要自行添加或删除空格。
            2. [辅助页码文件]：根据同名规则自行定位并读取companion文件`同名.pages.json`，将其作为**页码定位的优先依据**。
               - **重要**：如果Markdown路径是`D:\\outputs\\xxx.md`，则pages.json路径必须是`D:\\outputs\\xxx.pages.json`
               - **严禁**在文件名中添加任何额外字符（如`_B`、`_A`等后缀）。
               - **严禁**修改文件名的任何部分，只需将`.md`替换为`.pages.json`。
            3. [章节定位]：在文档中搜索"引用文件"或"参考文件"章节（包括可能的子章节）。
               - 常见章节标题包括："引用文件"、"参考文件"、"参考文献"、"规范性引用文件"等。
               - 需要识别章节标题及其所在页码。
            4. [文件提取]：从识别到的章节中提取各个文件的信息：
               - **文件编号/文件标识**：这是最重要的字段，通常格式如"GB/T xxxx"、"ISO xxxx"、"DO-xxx"、"ARPxxxx"等。
               - **文件名称**：如果存在，一并提取作为辅助展示。
               - **来源页码**：记录每个文件所在的页码。
            5. [数据输出]：生成一份JSON格式的结构化清单，格式如下：
               ```json
               {
                   "has_reference_section": true/false,
                   "reference_section_title": "章节标题",
                   "reference_section_page": "章节所在页码",
                   "reference_files": [
                       {
                           "file_id": "文件编号或文件标识",
                           "file_name": "文件名称（如有）",
                           "source_page": "来源页码"
                       }
                   ]
               }
               ```

            **关键指令**：
            - 你必须使用`Read File`工具读取Markdown文件和pages.json文件。
            - **pages.json路径构造规则**：将Markdown路径的`.md`后缀替换为`.pages.json`，不做任何其他修改。
            - 如果未找到"引用文件"或"参考文件"章节，`has_reference_section`必须为`false`。
            - 如果找到章节但无法提取文件，`reference_files`数组为空。
            - 最终结果必须放在`Final Answer:`之后，且必须是有效的JSON格式。
            - **严禁**在`Action:`之前输出任何对话式文本或报告摘要。
            """,
            expected_output="一份包含引用文件章节状态和文件清单的JSON格式报告。",
            agent=agent,
            context=[parse_task],
            max_retries=3
        )

    def a_round_check_task(self, agent, extract_task, parse_task):
        return Task(
            description="""
            【阶段三：A轮核验】
            基于上一阶段提取的引用文件清单，逐个核验各文件是否在正文中至少出现两次。
            
            1. [读取数据]：读取Markdown文件和pages.json文件。
               - **pages.json路径构造规则**：将Markdown路径的`.md`后缀替换为`.pages.json`，不做任何其他修改。
               - **严禁**在文件名中添加任何额外字符（如`_B`、`_A`等后缀）。
            2. [获取引用文件清单]：从上一阶段的输出中获取引用文件列表。
            3. [逐个核验]：对每个引用文件：
               - 使用文件编号/文件标识在全文中进行检索。
               - 统计在正文中的出现次数（**不包括**"引用文件"或"参考文件"章节本身）。
               - 记录每次出现的页码和原文片段（前后约50字）。
            4. [数据输出]：生成一份JSON格式的核验结果，格式如下：
               ```json
               {
                   "check_results": [
                       {
                           "file_id": "文件编号或文件标识",
                           "file_name": "文件名称（如有）",
                           "source_page": "来源页码",
                           "hit_count": 正文中出现的次数,
                           "hit_pages": ["页码1", "页码2", ...],
                           "evidence": [
                               {
                                   "page": "页码",
                                   "context": "原文片段"
                               }
                           ]
                       }
                   ]
               }
               ```

            **关键指令**：
            - 必须使用`Read File`工具读取Markdown文件和pages.json文件。
            - 正文核验时，**不得**将"引用文件"或"参考文件"章节自身作为正文引用次数。
            - 每个文件至少出现两次才算满足要求。
            - 最终结果必须放在`Final Answer:`之后，且必须是有效的JSON格式。
            """,
            expected_output="一份包含每个引用文件正文命中情况的JSON格式核验报告。",
            agent=agent,
            context=[extract_task, parse_task],
            max_retries=3
        )

    def b_round_check_task(self, agent, extract_task, parse_task):
        return Task(
            description="""
            【阶段四：B轮核验】
            作为独立的复核者，对A轮识别出的文件再次独立检索。
            
            1. [读取数据]：重新读取Markdown文件和pages.json文件。
               - **pages.json路径构造规则**：将Markdown路径的`.md`后缀替换为`.pages.json`，不做任何其他修改。
               - **严禁**在文件名中添加任何额外字符（如`_B`、`_A`等后缀）。
            2. [获取引用文件清单]：从上一阶段的输出中获取引用文件列表。
            3. [独立复核]：对每个引用文件：
               - 重新验证文件编号/文件标识是否提取正确。
               - 重新统计正文命中次数（**不包括**"引用文件"或"参考文件"章节本身）。
               - 检查是否误把"引用文件"章节本身计入正文命中次数。
            4. [数据输出]：生成一份独立的JSON格式复核结果，格式与A轮相同。

            **关键指令**：
            - 必须严格遵循`Thought` -> `Action` -> `Observation`的ReAct模式。
            - **严禁**在`Action:`之前输出任何报告内容。
            - 必须独立执行核验，不要参考A轮结果。
            - 最终结果必须放在`Final Answer:`之后，且必须是有效的JSON格式。
            """,
            expected_output="一份独立的、用于比对验证的JSON格式复核报告。",
            agent=agent,
            context=[extract_task, parse_task],
            max_retries=3
        )

    def cross_validation_task(self, agent, a_round_task, b_round_task, extract_task, parse_task):
        return Task(
            description="""
            【阶段五：交叉验证】
            对A轮与B轮的差异项进行复核，形成最终结论。
            
            1. [读取数据]：读取Markdown文件和pages.json文件。
               - **pages.json路径构造规则**：将Markdown路径的`.md`后缀替换为`.pages.json`，不做任何其他修改。
               - **严禁**在文件名中添加任何额外字符（如`_B`、`_A`等后缀）。
            2. [获取A轮和B轮结果]：从上一阶段的输出中获取A轮和B轮的核验结果。
            3. [差异比对]：
               - 比对A轮和B轮的核验结果。
               - 识别差异项（命中次数不一致、页码不一致等）。
            4. [原文复核]：
               - 对于差异项，必须回到原文重新确认。
               - 使用`Read File`工具读取相关页码的内容进行验证。
            5. [最终结果]：
               - 生成最终有效的核验结果。
               - 列出异常文件清单（未出现或出现次数不足的文件）。
            6. [数据输出]：生成一份JSON格式的最终结果，格式如下：
               ```json
               {
                   "final_results": [
                       {
                           "file_id": "文件编号或文件标识",
                           "file_name": "文件名称（如有）",
                           "source_page": "来源页码",
                           "a_round_count": A轮命中次数,
                           "b_round_count": B轮命中次数,
                           "final_count": 最终命中次数,
                           "hit_pages": ["页码1", "页码2", ...],
                           "is_satisfied": true/false,
                           "evidence": [
                               {
                                   "page": "页码",
                                   "context": "原文片段"
                               }
                           ]
                       }
                   ],
                   "exception_files": [
                       {
                           "file_id": "文件编号或文件标识",
                           "file_name": "文件名称（如有）",
                           "source_page": "来源页码",
                           "hit_count": 命中次数,
                           "reason": "未出现或出现次数不足"
                       }
                   ],
                   "validation_status": "完全一致/存在分歧但已通过原文核定/仍有存疑"
               }
               ```

            **关键指令**：
            - 当且仅当发现不一致时，才调用工具进行原文验证。
            - 最终输出必须以`Final Answer:`开头，后跟JSON格式的报告。
            - **严禁**输出`Thought:`或`Action:`作为最终答案的一部分。
            - 如果存在分歧，请在报告中说明分歧点和核定结果。
            """,
            expected_output="一份包含最终核验结果和异常文件清单的JSON格式报告。",
            agent=agent,
            context=[a_round_task, b_round_task, extract_task, parse_task],
            max_retries=3
        )

    def generate_report_task(self, agent, cross_validation_task, extract_task, file_name):
        return Task(
            description=f"""
            【阶段六：报告生成】
            基于交叉验证的最终结果，生成一份完整的Markdown格式审查报告。
            
            报告必须严格遵循以下Markdown格式：
            
            # 引用文件使用情况检查报告


            ## 1. 审查任务信息
            | 项目 | 详情 |
            | :--- | :--- |
            | 审查点 | 是否有"引用文件"章节，且章节中包含的文件是否在正文中都有引用？ |
            | 文件名称 | {file_name} |
            | 审查结果 | **[通过/不通过]** |

            ## 2. 审查依据
            | 项目 | 详情 |
            | :--- | :--- |
            | 审查依据 | AVICAS-312-100-T001《软件合格审定计划模板》 |
            | 取值字段 | 引用文件 / 参考文件，文件编号 / 文件标识 |
            | 取值位置 | 引用文件或参考文件章节及其子章节、正文 |

            ## 3. 引用文件提取结果
            | 序号 | 文件编号/文件标识 | 文件名称 | 来源页码 |
            | :--- | :--- | :--- | :--- |
            | 1 | [文件编号] | [文件名称] | [页码] |
            | ... | ... | ... | ... |

            ## 4. 核验结果
            | 文件编号/文件标识 | 最终命中次数 | 正文命中页码 | 是否满足"至少出现两次" | 原文依据 |
            | :--- | :--- | :--- | :--- | :--- |
            | [文件编号] | [次数] | [页码] | [是/否] | [原文片段，如有多条用分号分隔，如未全部列出则在末尾加"等等"] |
            | ... | ... | ... | ... | ... |

            ## 5. 异常项
            [如果存在异常文件，列出如下；如果无异常，显示"未发现异常文件"]
            
            | 文件编号/文件标识 | 来源位置 | 正文命中情况 | 原文依据 |
            | :--- | :--- | :--- | :--- |
            | [文件编号] | [页码] | [次数]次 | [原文片段，如有多条用分号分隔，如未全部列出则在末尾加"等等"] |
            | ... | ... | ... | ... |

            ## 6. 判定说明
            [简洁说明最终为什么通过、不通过或无法判定]

            **关键指令**：
            - 最终输出必须是一份完整的Markdown格式报告。
            - 报告必须以`# 引用文件使用情况检查报告`开头。
            - 所有表格必须格式规范，使用Markdown表格语法。
            - 如果审查通过，"审查结果"应为"**通过**"；如果不通过，应为"**不通过**"。
            - 原文依据必须单独展示，不得只给结论不给依据。
            - 原文依据如果有多条，用分号分隔；如果未全部列出，必须在末尾添加"等等"字样。
            """,
            expected_output="一份完整的、格式规范的Markdown格式审查报告。",
            agent=agent,
            context=[cross_validation_task, extract_task],
            max_retries=2
        )

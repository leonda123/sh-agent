from crewai import Task
import os


class CrossReferenceTasks:
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

    def a_round_check_task(self, agent, parse_task):
        return Task(
            description="""
            【阶段二：A轮核验】
            基于提取出的全文文本，执行一次精确全文检索。
            
            1. [读取数据]：读取上一个任务生成的Markdown文件。注意：必须使用上一步输出的精确路径，不要自行添加或删除空格。
            2. [执行检索]：使用`Full Text Search`工具在全文中搜索"错误!未找到引用源。"。
            3. [结果分析]：
               - 若未命中：输出"全文未检索到该字段"
               - 若命中：统计命中次数，并记录每次命中的原文片段（前后约50字）
            4. [数据输出]：生成一份JSON格式的检索结果，格式如下：
               ```json
               {
                   "search_term": "错误!未找到引用源。",
                   "hit_count": 命中次数（整数）,
                   "is_hit": true/false,
                   "hits": [
                       {
                           "position": 字符位置,
                           "context": "原文片段"
                       }
                   ]
               }
               ```

            **关键指令**：
            - 必须使用`Full Text Search`工具进行检索。
            - 检索字段固定为"错误!未找到引用源。"，不得修改。
            - 最终结果必须放在`Final Answer:`之后，且必须是有效的JSON格式。
            - **严禁**在`Action:`之前输出任何对话式文本或报告摘要。
            """,
            expected_output="一份包含全文检索结果的JSON格式报告。",
            agent=agent,
            context=[parse_task],
            max_retries=3
        )

    def b_round_check_task(self, agent, parse_task):
        return Task(
            description="""
            【阶段三：B轮核验】
            作为独立的复核者，基于逐页文本再次独立检索"错误!未找到引用源。"。
            
            1. [读取数据]：读取pages.json文件（根据Markdown路径推导）。
               - **pages.json路径构造规则**：将Markdown路径的`.md`后缀替换为`.pages.json`，不做任何其他修改。
               - **严禁**在文件名中添加任何额外字符。
            2. [执行检索]：使用`Page By Page Search`工具逐页搜索"错误!未找到引用源。"。
            3. [重点复核]：
               - 是否存在漏检页
               - 命中次数是否统计一致
               - 命中页码是否统计一致
            4. [数据输出]：生成一份独立的JSON格式复核结果，格式如下：
               ```json
               {
                   "search_term": "错误!未找到引用源。",
                   "total_hit_count": 总命中次数,
                   "hit_page_count": 命中页数,
                   "is_hit": true/false,
                   "page_hits": [
                       {
                           "page_label": "页码",
                           "hit_count": 该页命中次数,
                           "hits": [
                               {
                                   "context": "原文片段"
                               }
                           ]
                       }
                   ]
               }
               ```

            **关键指令**：
            - 必须严格遵循`Thought` -> `Action` -> `Observation`的ReAct模式。
            - **严禁**在`Action:`之前输出任何报告内容。
            - 必须独立执行检索，不要参考A轮结果。
            - 最终结果必须放在`Final Answer:`之后，且必须是有效的JSON格式。
            """,
            expected_output="一份独立的、用于比对验证的逐页检索JSON格式报告。",
            agent=agent,
            context=[parse_task],
            max_retries=3
        )

    def cross_validation_task(self, agent, a_round_task, b_round_task, parse_task):
        return Task(
            description="""
            【阶段四：交叉验证】
            对A轮与B轮的差异项进行复核，形成最终统一的检索结果。
            
            1. [获取A轮和B轮结果]：从上一阶段的输出中获取A轮和B轮的检索结果。
            2. [差异比对]：
               - 比对A轮和B轮的命中次数是否一致
               - 比对命中页码是否一致
            3. [原文复核]：
               - 若结果不一致，必须回到原文逐页确认
               - 使用`Full Text Search`或`Page By Page Search`工具重新验证
            4. [最终结果]：
               - 生成最终统一的检索结果
               - 明确说明是否命中、命中次数、命中页码和原文依据
            5. [数据输出]：生成一份JSON格式的最终结果，格式如下：
               ```json
               {
                   "search_term": "错误!未找到引用源。",
                   "final_hit_count": 最终命中次数,
                   "is_hit": true/false,
                   "hit_pages": ["页码1", "页码2", ...],
                   "evidence": [
                       {
                           "page": "页码",
                           "context": "原文片段"
                       }
                   ],
                   "validation_status": "完全一致/存在分歧但已通过原文核定/仍有存疑",
                   "a_round_count": A轮命中次数,
                   "b_round_count": B轮命中次数
               }
               ```

            **关键指令**：
            - 当且仅当发现不一致时，才调用工具进行原文验证。
            - 最终输出必须以`Final Answer:`开头，后跟JSON格式的报告。
            - **严禁**输出`Thought:`或`Action:`作为最终答案的一部分。
            - 如果存在分歧，请在报告中说明分歧点和核定结果。
            """,
            expected_output="一份包含最终统一检索结果的JSON格式报告。",
            agent=agent,
            context=[a_round_task, b_round_task, parse_task],
            max_retries=3
        )

    def build_result_task(self, agent, cross_validation_task, parse_task, file_name):
        return Task(
            description=f"""
            【阶段五：结果生成】
            基于交叉验证的最终结果，生成一份完整的Markdown格式审查报告。
            
            报告必须严格遵循以下Markdown格式：
            
            # 交叉引用正确性检查报告


            ## 1. 审查任务信息
            | 项目 | 详情 |
            | :--- | :--- |
            | 审查项 | 正文中所有上下文引用是否正确、一致？交叉索引；文件章节标题、标题名称等。 |
            | 文件名称 | {file_name} |
            | 审查结果 | **[通过/不通过/无法判定]** |

            ## 2. 审查结果
            | 项目 | 详情 |
            | :--- | :--- |
            | 审查结果 | [通过/不通过/无法判定] |
            | 业务逻辑结果 | [是/否/无法判定] |
            | 结论描述 | [上传的{file_name}中的交叉引用正确/不正确/由于文档无法完成有效检索，未能得出交叉引用正确性结论] |

            ## 3. 审查依据
            | 项目 | 详情 |
            | :--- | :--- |
            | 检索字段 | 错误!未找到引用源。 |
            | 检索范围 | 全文 |
            | 检索方法 | 全文精确检索 + 逐页复核 |

            ## 4. 检索结果
            | 项目 | 详情 |
            | :--- | :--- |
            | 是否命中 | [是/否] |
            | 命中次数 | [整数] |
            | 命中页码 | [页码1, 页码2, ...] |

            ### 原文依据
            [如果命中，列出每次命中的原文片段；如果未命中，显示"全文未检索到该字段"]
            
            | 序号 | 页码 | 原文片段 |
            | :--- | :--- | :--- |
            | 1 | [页码] | [原文片段] |
            | ... | ... | ... |

            ## 5. 判定说明
            [简洁说明最终为什么通过、不通过或无法判定]

            **判定规则**：
            1. 若全文未检索到"错误!未找到引用源。"，则：
               - 审查结果：通过
               - 业务逻辑结果：是
               - 结论描述：上传的{file_name}中的交叉引用正确
            
            2. 若全文检索到"错误!未找到引用源。"，则：
               - 审查结果：不通过
               - 业务逻辑结果：否
               - 结论描述：上传的{file_name}中的交叉引用不正确
            
            3. 若无法完成有效全文检索，则：
               - 审查结果：无法判定
               - 业务逻辑结果：无法判定
               - 结论描述：由于文档无法完成有效检索，未能得出交叉引用正确性结论

            **关键指令**：
            - 最终输出必须是一份完整的Markdown格式报告。
            - 报告必须以`# 交叉引用正确性检查报告`开头。
            - 所有表格必须格式规范，使用Markdown表格语法。
            - 如果审查通过，"审查结果"应为"**通过**"；如果不通过，应为"**不通过**"；如果无法判定，应为"**无法判定**"。
            - 原文依据必须单独展示，不得只给结论不给依据。
            - 若未命中，"命中页码"显示"无"，"原文依据"显示"全文未检索到该字段"。
            """,
            expected_output="一份完整的、格式规范的Markdown格式审查报告。",
            agent=agent,
            context=[cross_validation_task, parse_task],
            max_retries=2
        )

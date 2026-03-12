# 文档审计智能体 (Document Audit Agent)

这是一个基于 CrewAI 和 FastAPI 的智能文档审计系统。它旨在自动审核 PDF 文档中的特定检查项，目前主要支持图表清单与正文内容的一致性检查。

## 功能特性

*   **PDF 文档转换**: 使用 `pdf2docx` 和 `markitdown` 将 PDF 转换为 Markdown 格式，尽可能保留原始结构。
*   **多智能体协同**:
    *   **文档处理专家**: 负责文档格式转换。
    *   **内容分析师**: 负责从文档中提取图/表目录以及正文中的图/表引用。
    *   **审计员**: 负责比对目录与正文内容，发现不一致之处。
    *   **审查员**: 负责复核审计结果并生成最终报告。
*   **Web 界面**: 提供简单的 Web 界面用于上传文件和查看实时审计日志。
*   **REST API**: 提供标准的 API 接口，方便集成。

## 项目结构

```text
doc_audit_agent/
├── api/
│   ├── app.py             # FastAPI 应用入口
│   └── routes.py          # API 路由定义
├── core/
│   ├── agents/
│   │   └── figure_table_checker/  # 图表检查智能体群
│   │       ├── agents.py          # 智能体定义
│   │       ├── tasks.py           # 任务定义
│   │       ├── crew.py            # Crew 编排
│   │       └── prompts/           # 持久化的中文提示词 (.md)
│   └── tools/
│       ├── document_tools.py      # CrewAI 工具封装
│       └── file_converter.py      # 文件转换逻辑 (PDF->Docx->MD)
├── frontend/
│   └── index.html         # 中文 Web 界面
├── uploads/               # 上传文件临时存储
├── outputs/               # 转换后的 Markdown 文件存储
├── main.py                # 启动脚本
└── requirements.txt       # 项目依赖
```

## 快速开始

### 1. 环境准备

确保已安装 Python 3.10+。

### 2. 安装依赖

```bash
pip install -r doc_audit_agent/requirements.txt
```

### 3. 配置环境变量

在 `doc_audit_agent/.env` 文件中配置阿里云模型接口信息（已默认配置，如需更改请编辑该文件）：

```env
ALIYUN_API_KEY=your_api_key
ALIYUN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
```

### 4. 启动服务

```bash
python doc_audit_agent/main.py
```

### 5. 使用系统

*   **Web 界面**: 访问 [http://localhost:5000/ui](http://localhost:5000/ui)
*   **API 文档**: 访问 [http://localhost:5000/docs](http://localhost:5000/docs)

## 扩展指南

如果需要添加新的检查项（例如“错别字检查”），可以按照以下步骤操作：

1.  在 `core/agents/` 下创建一个新目录，例如 `spell_checker`。
2.  定义新的 `agents.py` 和 `tasks.py`。
3.  创建新的 `crew.py` 进行编排。
4.  在 `api/routes.py` 中添加新的 API 端点来调用新的 Crew。

## 许可证

MIT License

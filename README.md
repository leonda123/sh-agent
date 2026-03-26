# SH Agent Platform (智能体平台)

这是一个基于 CrewAI 和 FastAPI 构建的模块化多智能体平台，文档审计设计。它支持动态加载和运行不同的智能体插件，目前内置了**文档图表一致性审计**和**术语/缩略语一致性审计**智能体。

## 功能特性

*   **模块化架构**: 核心平台与智能体插件分离，遵循 `BaseAgent` 统一接口，易于扩展。
*   **统一 API**: 提供标准的 REST API 接口，用于管理和运行智能体任务。
*   **实时流式反馈**: 基于 Server-Sent Events (SSE) 技术，实时推送智能体思考过程、工具调用和执行进度。
*   **多维度审计**:
    *   **文档图表一致性 (`doc_audit`)**: 自动核对文档中的图表目录与正文内容的一致性。
    *   **术语/缩略语一致性 (`doc_term`)**: 检查术语定义、缩略语对照表与全文引用的一致性，支持跨平台全文检索。
*   **高性能文档处理**: 集成 `pdf2docx` 和 `markitdown` 工具链，支持将复杂 PDF 转换为高质量 Markdown 供 LLM 分析。
*   **现代 Web UI**: 提供直观的界面，支持文件上传、任务监控、实时日志查看及报告下载。
*   **跨平台支持**: 提供 Docker 封装，支持 Windows、macOS 和 Linux 环境的一键部署。

## 快速开始

### 1. 环境准备

确保已安装 Python 3.11+ 或 Docker。

### 2. 配置环境变量

在项目根目录创建 `.env` 文件（或参考 `docker-compose.yml` 中的环境变量设置）：

```env
ALIYUN_API_KEY=your_api_key
ALIYUN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max
```

### 3. 使用 Docker 部署 (推荐)

使用 Docker 可以快速在任何平台上启动服务，且避免了复杂的依赖安装：

```bash
# 构建并启动服务
docker-compose up -d
```

服务将启动在 `http://localhost:5050`。

### 4. 本地开发环境启动

如果你希望在本地运行：

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py
```

默认访问地址为 `http://localhost:5050/ui`。

## 使用指南

1.  **访问界面**: 打开浏览器访问 `http://localhost:5050/ui`。
2.  **选择智能体**: 在页面左侧选择需要的审计类型（如“术语/缩略语一致性审计”）。
3.  **上传文件**: 点击上传区域，选择需要审计的 PDF 或 Markdown 文档。
4.  **查看进度**: 系统会实时展示智能体的思考步骤和执行日志。
5.  **获取报告**: 审计完成后，点击“下载报告”获取详细的 Markdown 审计结论。

## API 概览

*   `GET /api/agents`: 获取所有可用的智能体。
*   `POST /api/run/{agent_id}`: 启动指定智能体任务。
*   `GET /api/stream/{session_id}`: 订阅任务实时状态流 (SSE)。
*   `GET /api/result/{session_id}`: 获取任务最终审计结果。
*   `GET /docs`: 查看完整的 Swagger API 文档。

## 目录结构

```text
.
├── agents/             # 智能体插件目录
│   ├── doc_audit/      # 图表一致性审计智能体
│   └── doc_term/       # 术语一致性审计智能体
├── app/                # 核心框架代码
│   ├── api/            # API 路由
│   ├── core/           # 智能体管理、LLM 工厂、执行器
│   └── tools/          # 文档处理工具集
├── frontend/           # 前端静态资源
├── Dockerfile          # 容器构建文件
├── docker-compose.yml  # 容器编排文件
└── main.py             # 入口程序
```

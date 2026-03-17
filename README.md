# SH Agent Platform (智能体文档审计平台)

这是一个基于 CrewAI 和 FastAPI 构建的模块化多智能体平台。它支持动态加载和运行不同的智能体插件，目前内置了**文档图表一致性审计**智能体。

## 功能特性

*   **模块化架构**: 核心平台与智能体插件分离，易于扩展新的智能体。
*   **统一 API**: 提供标准的 REST API 接口，用于列出、运行和停止智能体任务。
*   **实时反馈**: 基于 Server-Sent Events (SSE) 技术，实时推送智能体执行步骤和日志。
*   **PDF 文档处理**: 内置 `pdf2docx` 和 `markitdown` 工具链，将 PDF 转换为高质量 Markdown。
*   **Web 界面**: 提供直观的 Web 界面，支持选择智能体、上传文件、查看实时进度和下载报告。

## 快速开始

### 1. 环境准备

确保已安装 Python 3.10+。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

在项目根目录创建或修改 `.env` 文件，配置大模型接口信息：

```env
ALIYUN_API_KEY=your_api_key
ALIYUN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
OPENAI_API_KEY=NA  # 如果使用兼容接口，此项可设为任意值
```

### 4. 启动服务

在项目根目录下运行：

```bash
python main.py
```

服务将启动在 `http://0.0.0.0:5000`。

### 5. 使用系统

*   **Web 界面**: 访问 [http://localhost:5000/ui](http://localhost:5000/ui)
*   **API 文档**: 访问 [http://localhost:5000/docs](http://localhost:5000/docs)

## API 接口文档

平台提供以下核心 API 接口：

### 1. 获取智能体列表

*   **URL**: `/api/agents`
*   **Method**: `GET`
*   **描述**: 获取当前平台所有可用的智能体。
*   **Response**:
    ```json
    [
      {
        "id": "doc_audit",
        "name": "文档图表一致性审计",
        "description": "自动检查文档中的图表目录与正文内容是否一致。"
      }
    ]
    ```

### 2. 运行智能体

*   **URL**: `/api/run/{agent_id}`
*   **Method**: `POST`
*   **Content-Type**: `multipart/form-data`
*   **Parameters**:
    *   `agent_id` (path): 智能体 ID (例如 `doc_audit`)
    *   `file` (form-data): 要处理的 PDF 文件
*   **Response**:
    ```json
    {
      "session_id": "uuid-string",
      "message": "Agent started",
      "file_path": "uploads/uuid_filename.pdf"
    }
    ```

### 3. 监听任务进度 (SSE)

*   **URL**: `/api/stream/{session_id}`
*   **Method**: `GET`
*   **Content-Type**: `text/event-stream`
*   **描述**: 通过 SSE 连接实时接收任务日志和状态更新。
*   **Events**:
    *   `start`: 任务开始
    *   `step`: 智能体思考/行动步骤
    *   `task_completed`: 阶段性任务完成（用于前端进度条）
    *   `result`: 最终结果
    *   `error`: 错误信息
    *   `stop`: 任务被用户停止

### 4. 停止任务

*   **URL**: `/api/stop/{session_id}`
*   **Method**: `POST`
*   **Response**:
    ```json
    {
      "message": "Stop signal sent to session {session_id}"
    }
    ```

## 扩展开发指南

平台支持**自动发现**机制。要添加新的智能体，请遵循以下步骤：

1.  在 `agents/` 目录下创建一个新目录（例如 `agents/my_agent`）。
2.  推荐的目录结构：
    ```text
    agents/my_agent/
    ├── agent.py      # 实现 BaseAgent 接口 (核心逻辑)
    ├── roles.py      # 定义角色 (Agents)
    ├── tasks.py      # 定义任务 (Tasks)
    └── prompts/      # 存放提示词模板 (*.md)
    ```
3.  在 `agent.py` 中实现 `BaseAgent` 接口，并使用 `LLMFactory` 管理模型：

    ```python
    from app.core.base_agent import BaseAgent
    from app.core.llm import LLMFactory

    class MyAgent(BaseAgent):
        @property
        def name(self) -> str:
            return "my_agent_id"
        
        @property
        def display_name(self) -> str:
            return "我的自定义智能体"
            
        def run(self, inputs, queue, stop_event):
            # 1. 获取模型
            llm = LLMFactory.get_aliyun_llm()
            # 2. 实现智能体逻辑
            pass
    ```

4.  **自动注册**：系统启动时会自动扫描并加载 `agents/` 下的所有合法智能体，无需手动注册。

## 许可证

MIT License

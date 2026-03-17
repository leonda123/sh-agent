# 智能体开发流程指南

## 概述

本项目已实现核心执行逻辑与业务逻辑的完全分离。开发者只需在 `agents/` 目录下按照规范创建智能体文件，系统会自动完成以下工作：
- 自动发现并注册智能体
- 自动管理后台执行线程
- 自动处理日志流式传输 (SSE)
- 自动持久化执行历史

## 详细开发步骤

### 1. 创建智能体目录

在 `agents/` 目录下创建一个新的文件夹，文件夹名称建议使用英文小写（如 `contract_review`）。

```bash
agents/
  └── contract_review/
      ├── agent.py      # 核心类，实现 BaseAgent 接口
      ├── roles.py      # 定义角色 (Agents)
      ├── tasks.py      # 定义任务 (Tasks)
      └── prompts/      # 存放提示词模板 (*.md)
```

### 2. 实现智能体类

在 `agent.py` 中，创建一个类继承自 `app.core.base_agent.BaseAgent`。你需要利用 `app.core.llm.LLMFactory` 来获取模型实例，并组织 `roles.py` 和 `tasks.py` 中的逻辑。

#### 示例代码模板

```python
from app.core.base_agent import BaseAgent
from app.core.llm import LLMFactory
from queue import Queue
from threading import Event
from .roles import MyRoles
from .tasks import MyTasks
from crewai import Crew

class ContractReviewAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "contract_review"

    @property
    def display_name(self) -> str:
        return "合同审查助手"

    @property
    def description(self) -> str:
        return "审查合同风险点和合规性，输出风险报告。"

    def run(self, inputs: dict, queue: Queue, stop_event: Event):
        # 1. 获取 LLM 实例
        llm = LLMFactory.get_aliyun_llm()
        
        # 2. 定义回调用于流式输出
        def step_callback(step):
            queue.put({"type": "step", "agent": "审查员", "phase_id": "phase_1", "content": str(step)})

        # 3. 初始化角色与任务
        roles = MyRoles()
        reviewer = roles.reviewer_agent(llm, step_callback)
        
        tasks = MyTasks()
        review_task = tasks.review_task(reviewer, inputs['file_path'])

        # 4. 构建并执行 Crew
        crew = Crew(agents=[reviewer], tasks=[review_task], verbose=True)
        
        # 检查停止信号
        if stop_event.is_set():
            return "任务已取消"
            
        result = crew.kickoff()
        return str(result)
```

### 3. 验证与测试

系统支持**自动发现**，无需配置任何路由或注册代码。

1. **启动/重启服务**。
2. **访问接口**：
   - `GET /api/agents`：确认新智能体出现在列表中。
   - `POST /api/run/{agent_name}`：上传文件并启动测试。
   - `GET /api/stream/{session_id}`：观察实时流式日志。
3. **查看日志**：
   - 访问 `GET /api/stream/{session_id}` 查看实时流。

## 进阶功能

### 使用 LLM

系统已集成 `litellm` 并自动配置了回调。在 `run` 方法中直接调用 `litellm.completion` 或使用 `CrewAI` 等框架，输入输出会自动记录到历史日志中。

### 错误处理

若 `run` 方法抛出异常，`AgentRunner` 会自动捕获并发送 `error` 事件。建议在业务逻辑中自行捕获预期内的错误，并通过 `queue.put({"type": "error", ...})` 发送更友好的错误信息。

### 停止机制

务必在耗时操作（如循环、长文本处理）中定期检查 `if stop_event.is_set(): return`，以响应用户的停止请求。

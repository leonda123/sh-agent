import os
from typing import Any, Dict, Optional

from app.core.llm import LLMFactory


class FirstPageAuditRoles:
    ROLE_PHASE_MAP = {
        "文档解析员": "phase_1",
        "首页要素提取员": "phase_2",
        "结论生成员": "phase_3",
    }

    ROLE_PROMPTS = {
        "文档解析员": "parser_backstory.md",
        "首页要素提取员": "extractor_backstory.md",
        "结论生成员": "reporter_backstory.md",
    }

    def __init__(self, phase_llm_config: Optional[Dict[str, Dict[str, Any]]] = None):
        self.phase_llm_config = phase_llm_config or {}
        self.default_llm = LLMFactory.get_aliyun_llm()

    def load_prompt(self, filename: str) -> str:
        path = os.path.join(os.path.dirname(__file__), "prompts", filename)
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()

    def get_role_prompt(self, role_name: str) -> str:
        filename = self.ROLE_PROMPTS[role_name]
        return self.load_prompt(filename)

    def get_llm_for_phase(self, phase_id: str):
        config = self.phase_llm_config.get(phase_id)
        if config:
            return LLMFactory.get_llm(config)
        return self.default_llm

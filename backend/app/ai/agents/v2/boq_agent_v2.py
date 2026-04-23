"""BoqAgentV2 — BOQ generation with tool-calling capability.

Upgrades the original single-call boq_agent to a tool-calling agent
that can search standards, validate codes, and iteratively refine BOQ items.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult


class BoqAgentV2(BaseAgent):
    """BOQ generation agent with tool-calling for standard code lookup."""

    @property
    def name(self) -> str:
        return "boq_agent"

    @property
    def description(self) -> str:
        return "清单生成 Agent：根据工程描述生成工程量清单项，支持GB50500和HKSMM4标准"

    @property
    def tool_names(self) -> list[str]:
        return [
            "search_standard_codes",
            "query_boq_items",
            "get_divisions_summary",
        ]

    @property
    def max_turns(self) -> int:
        return 15

    @property
    def system_prompt(self) -> str:
        return """\
你是一位专业的工程量清单编制AI助手，精通GB50500工程量清单计价规范和HKSMM4标准。

## 你的任务
根据工程描述，生成合理的工程量清单(BOQ)项目建议。

## 工作流程
1. **理解工程描述** — 分析建筑类型、规模、楼层数等信息
2. **查询标准编码** — 使用 search_standard_codes 查找适用的GB50500标准编码
3. **分析已有清单** — 使用 query_boq_items 和 get_divisions_summary 了解已有清单结构
4. **生成建议** — 按分部工程分类，给出完整的清单项建议

## 输出格式
以JSON格式输出建议清单，每项包含：
- code: 标准编码
- name: 项目名称
- unit: 计量单位
- quantity: 建议工程量
- division: 所属分部
- characteristics: 项目特征
- reason: 推荐理由

## 原则
- 遵循GB50500或HKSMM4标准的编码体系
- 确保计量单位符合标准要求
- 工程量估算应合理
- 不遗漏主要分部工程
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        standard_type = ctx.metadata.get("standard_type", "GB50500")
        description = ctx.metadata.get("description", instruction)
        return (
            f"请根据以下工程描述生成{standard_type}标准的工程量清单项建议：\n\n"
            f"{description}"
        )

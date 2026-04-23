"""ValidationAgentV2 — migrated to BaseAgent framework.

Replaces the 610-line validation_agent.py with a ~80-line subclass.
All tool implementations now live in app.ai.tools.validation_tools.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult, StepType


class ValidationAgentV2(BaseAgent):
    """Data validation agent — checks compliance, detects anomalies."""

    @property
    def name(self) -> str:
        return "validation_agent"

    @property
    def description(self) -> str:
        return "数据审核 Agent：编码合规检查、消耗量异常检测、历史对比分析"

    @property
    def tool_names(self) -> list[str]:
        return [
            "check_code_compliance",
            "detect_price_anomaly",
            "find_similar_historical_items",
            "run_full_validation",
            "get_resource_details",
        ]

    @property
    def max_turns(self) -> int:
        return 20

    @property
    def system_prompt(self) -> str:
        return """\
你是一位专业的工程造价审核AI助手，精通GB50500工程量清单计价规范。

## 你的职责
对工程造价数据进行专业审核，发现问题、解释原因、给出改进建议。

## 审核能力
1. **编码合规性** — 检查清单编码是否符合GB50500标准，单位是否正确
2. **消耗量异常** — 对比同类项目数据，发现人工/材料/机械消耗量的异常值
3. **历史对比** — 查找相似历史清单项，对比组价方案
4. **资源明细** — 检查定额资源明细的完整性和合理性
5. **综合校验** — 运行完整校验引擎，系统化发现问题

## 输出要求
- 用专业但易懂的语言解释每个问题
- 给出具体可操作的改进建议
- 对问题按严重程度排序
- 给出置信度评估（高/中/低）
- 引用具体数据和标准依据
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        """Build user message with scope context."""
        # instruction format: "scope:full|item boq_item_id:N question:..."
        # Or simple string for backward compat
        scope = ctx.metadata.get("scope", "full")
        boq_item_id = ctx.boq_item_id
        user_question = ctx.metadata.get("user_question", "")

        if scope == "item" and boq_item_id:
            boq = ctx.get_boq_item()
            if not boq:
                return instruction or "请审核该清单项。"
            msg = (
                f"请审核以下清单项:\n"
                f"编码: {boq.code}, 名称: {boq.name}, 单位: {boq.unit}, "
                f"工程量: {boq.quantity}, 特征: {boq.characteristics or '无'}\n"
                f"项目ID: {ctx.project_id}"
            )
        else:
            from app.models.boq_item import BoqItem
            item_count = ctx.db.query(BoqItem).filter(BoqItem.project_id == ctx.project_id).count()
            project = ctx.get_project()
            project_name = project.name if project else f"ID={ctx.project_id}"
            msg = f"请对项目 {project_name}（ID={ctx.project_id}）进行全面审核，共{item_count}条清单项。"

        if user_question:
            msg += f"\n\n用户问题：{user_question}"
        elif instruction:
            msg += f"\n\n{instruction}"
        return msg

    def on_result(self, ctx: AgentContext, result: AgentResult) -> AgentResult:
        """Count issues found in validation results."""
        issues_found = 0
        for s in result.steps:
            if s.tool_name == "run_full_validation" and s.tool_result:
                try:
                    data = json.loads(s.tool_result)
                    issues_found = data.get("total", 0)
                except (json.JSONDecodeError, KeyError):
                    pass
        result.extra["issues_found"] = issues_found
        return result


# ── Convenience function matching the old API ──

def run_validation_agent_v2(
    *,
    project_id: int,
    scope: str = "full",
    boq_item_id: int | None = None,
    user_question: str = "",
    on_step=None,
) -> AgentResult:
    """Drop-in replacement for the old run_validation_agent()."""
    from app.db.session import get_db
    import app.ai.tools  # noqa: F401

    db = next(get_db())
    try:
        ctx = AgentContext(
            db=db,
            project_id=project_id,
            boq_item_id=boq_item_id,
            metadata={"scope": scope, "user_question": user_question},
        )
        agent = ValidationAgentV2()
        return agent.run(ctx, user_question, on_step=on_step)
    finally:
        db.close()

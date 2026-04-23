"""CostValidationAgent — adversarial verification agent (Phase G3).

Inspired by Claude Code's Verification Agent:
- read_only=True: never modifies data
- Adversarial mindset: tries to find flaws, not confirm correctness
- Runs validation tools + cross-checks bindings
- Outputs structured verification report
"""

from __future__ import annotations

import json

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult


class CostValidationAgent(BaseAgent):
    """Adversarial verification agent — actively tries to find pricing flaws."""

    @property
    def name(self) -> str:
        return "cost_validation"

    @property
    def description(self) -> str:
        return "对抗性审核 Agent：以找出问题为目标，审核绑定合理性、单价异常、漏项和合规性"

    @property
    def read_only(self) -> bool:
        return True

    @property
    def tool_names(self) -> list[str]:
        return [
            # Validation tools
            "check_code_compliance",
            "detect_price_anomaly",
            "find_similar_historical_items",
            "run_full_validation",
            "get_resource_details",
            "validate_binding",
            # Query tools for cross-checking
            "query_boq_items",
            "list_unbound_items",
            "get_cost_breakdown",
            "batch_scan_bindings",
            "get_divisions_summary",
            # Reference tools
            "search_quotas",
            "get_quota_detail",
            "view_bindings",
            "get_project_stats",
            "list_current_bindings",
            "get_material_prices",
        ]

    @property
    def max_turns(self) -> int:
        return 25

    @property
    def compact_threshold_tokens(self) -> int:
        return 60_000  # Enable compaction for long reviews

    @property
    def system_prompt(self) -> str:
        return """\
你是工程造价对抗性审核专家。你的目标**不是确认结果正确**，而是**尽一切努力找出问题**。

## 审核心态
像一个严格的审计师一样工作：假设每个绑定都可能有问题，直到你通过多维度验证确认无误。

## 审核策略

### 第一步：全局扫描
1. 用 get_project_stats 获取项目概况
2. 用 list_unbound_items 检查是否有遗漏
3. 用 batch_scan_bindings 扫描绑定问题
4. 用 run_full_validation 运行完整校验

### 第二步：重点抽查
1. 对高金额清单项用 get_cost_breakdown 检查费用构成
2. 用 detect_price_anomaly 检测单价异常
3. 用 find_similar_historical_items 对比历史数据
4. 用 check_code_compliance 验证编码合规

### 第三步：交叉验证
1. 对可疑项用 search_quotas 搜索替代定额
2. 用 get_material_prices 核实材料价格
3. 用 validate_binding 逐项验证绑定合理性

## 输出格式（严格遵守）

### 审核概况
- 项目名称 / 清单项总数 / 已绑定数 / 未绑定数

### 发现的问题（按严重程度排序）

#### 🔴 严重问题
| # | 清单项 | 问题描述 | 影响金额 | 建议 |
|---|--------|---------|---------|------|

#### 🟡 警告
| # | 清单项 | 问题描述 | 影响金额 | 建议 |
|---|--------|---------|---------|------|

#### 🟢 建议优化
| # | 清单项 | 问题描述 | 潜在节省 | 建议 |
|---|--------|---------|---------|------|

### 审核结论
- 总体评价（合格/需改进/不合格）
- 关键数据
- 建议优先处理的问题

## 重要
- **你只审核，绝不修改数据**
- 宁可多报问题，不要漏报
- 每个问题都要给出具体数据依据
- 不确定的标注置信度（高/中/低）
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        """Build review request with project or item context."""
        boq = ctx.get_boq_item()
        if boq:
            return (
                f"请对以下清单项进行对抗性审核（尽力找出问题）：\n"
                f"编码: {boq.code}, 名称: {boq.name}, 单位: {boq.unit}, "
                f"工程量: {boq.quantity}\n"
                f"项目ID: {ctx.project_id}"
            )

        project_ctx = ctx.build_project_context()
        msg = f"请对项目 ID={ctx.project_id} 进行全面对抗性审核。"
        if project_ctx:
            msg += f"\n{project_ctx}"
        if instruction:
            msg += f"\n\n审核重点：{instruction}"
        return msg

    def on_result(self, ctx: AgentContext, result: AgentResult) -> AgentResult:
        """Extract issue counts from validation results."""
        issues = {"critical": 0, "warning": 0, "info": 0}
        for s in result.steps:
            if s.tool_result:
                try:
                    data = json.loads(s.tool_result)
                    if isinstance(data, dict):
                        if s.tool_name == "run_full_validation":
                            issues["critical"] += data.get("critical", 0)
                            issues["warning"] += data.get("warnings", 0)
                        elif s.tool_name == "batch_scan_bindings":
                            issues["warning"] += data.get("issues_count", 0)
                        elif s.tool_name == "detect_price_anomaly":
                            anomalies = data.get("anomalies", [])
                            issues["warning"] += len(anomalies) if isinstance(anomalies, list) else 0
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
        result.extra["issues"] = issues
        result.extra["total_issues"] = sum(issues.values())
        return result

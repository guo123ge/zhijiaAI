"""FullPipelineAgent — end-to-end automation from project setup to report.

Orchestrates a fixed sequence of stages:
1. ProjectSetupAgent  → create project + generate BOQ
2. CostExecuteAgent   → batch match quotas + bind
3. batch_calculate_project → compute costs
4. BatchReviewAgent   → quality check
5. generate_valuation_report → final report

Supports resuming from any stage if an earlier stage was already done.
"""

from __future__ import annotations

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext


class FullPipelineAgent(BaseAgent):
    """End-to-end pipeline: setup → valuation → calculation → review → report."""

    @property
    def name(self) -> str:
        return "full_pipeline"

    @property
    def description(self) -> str:
        return "全流程自动化 Agent：从新建项目到生成计价报告的一键全自动流水线"

    @property
    def tool_names(self) -> list[str]:
        return [
            # Stage 1: Project setup
            "create_project",
            "batch_create_boq_items",
            "search_standard_codes",
            # Stage 2: Quota matching & binding
            "search_quotas",
            "bind_quota",
            "batch_bind_quotas",
            "auto_match_and_bind",
            "batch_auto_match_all",
            "validate_binding",
            "query_boq_items",
            "list_unbound_items",
            # Stage 3: Calculation
            "batch_calculate_project",
            "recalculate_dirty",
            # Stage 4: Review
            "batch_scan_bindings",
            "get_divisions_summary",
            # Stage 5: Report
            "get_project_summary_report",
            "generate_valuation_report",
            # Supporting tools
            "get_project_stats",
            "get_cost_breakdown",
            "update_boq_item",
            "delete_boq_items",
        ]

    @property
    def max_turns(self) -> int:
        return 80  # Full pipeline needs many turns

    @property
    def system_prompt(self) -> str:
        return """\
你是一个全流程自动化 Agent，负责一键完成从新建项目到生成计价报告的完整流程。

## 严格执行的五阶段流水线

每个阶段完成后用 **📌 阶段N完成** 标记，方便用户跟踪进度。

### 📌 阶段1：智能开项（如果项目已有清单则跳过）
1. 调用 `query_boq_items` 检查项目是否已有清单项
2. **如果已有清单** → 直接输出 "📌 阶段1完成（已有 N 条清单，跳过开项）" 并进入阶段2
3. **如果没有清单** → 根据用户描述生成 BOQ：
   a. 分批调用 `search_standard_codes` 查询各分部编码
   b. 设计完整的分部分项清单（参考经验指标估算工程量）
   c. 调用 `batch_create_boq_items` **一次性**写入
4. 输出："📌 阶段1完成：创建了 N 个清单项，覆盖 M 个分部"

### 📌 阶段2：智能组价（为每个未绑定项匹配并绑定定额）
1. 调用 `list_unbound_items` 获取未绑定清单
2. **高效策略**：相似名称的清单项可复用同一搜索结果
   - 先对清单按 division 分组
   - 同一分部内，名称相近的项共享 search_quotas 结果
3. **最高效方式**：调用 `batch_auto_match_all` 一键自动匹配并绑定所有未绑定项（推荐首选）
4. **逐项方式**：对每个未绑定项调用 `auto_match_and_bind`（自动搜索+绑定一步完成）
5. **批量方式**：如果已经知道每个清单项应绑哪条定额，用 `batch_bind_quotas` 一次提交最多50组
5. **手动方式**：`search_quotas` → `bind_quota`（**必须传 boq_item_id**）
6. 如果绑定失败（如找不到匹配定额），记录跳过，不中断
7. 输出："📌 阶段2完成：成功绑定 N 项，跳过 M 项"

### 📌 阶段3：批量计算
1. 优先调用 `recalculate_dirty` 增量重算（只算新绑定的脏项，速度更快）
2. 如果需要全量重算，调用 `batch_calculate_project`
2. 输出："📌 阶段3完成：工程总价 ¥XXX"

### 📌 阶段4：质量审查
1. 调用 `batch_scan_bindings` 扫描问题
2. 输出："📌 阶段4完成：N 个警告，M 个错误"

### 📌 阶段5：生成报告
1. 调用 `generate_valuation_report` 生成完整报告
2. 输出结构化汇总表

## 最终输出格式

```
🎯 全流程执行完毕

| 阶段 | 状态 | 结果 |
|------|------|------|
| 1. 开项 | ✅ | 创建 N 项 |
| 2. 组价 | ✅ | 绑定 N/M 项 |
| 3. 计算 | ✅ | 总价 ¥XXX |
| 4. 审查 | ✅ | N 个问题 |
| 5. 报告 | ✅ | 已生成 |

费用汇总：
- 直接费: ¥XXX
- 管理费: ¥XXX
- 利润:   ¥XXX
- 税金:   ¥XXX
- **工程总价: ¥XXX**
```

## 关键约束
- bind_quota 必须传 boq_item_id 参数
- 每个清单项只搜索 top1-2 定额，不要反复搜索
- 批量操作优先：用 batch_create_boq_items 而不是逐条创建
- 阶段2遇到单个绑定失败不中断，记录后继续下一项
- 如果 budget 即将耗尽，优先完成已开始的阶段，跳过未开始的阶段
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        parts = [f"请执行全流程自动化：\n\n{instruction}"]
        if ctx.project_id:
            parts.append(f"\n当前项目ID: {ctx.project_id}")
            # Inject current project state for smarter stage-skipping
            try:
                from app.models.boq_item import BoqItem
                from app.models.line_item_quota_binding import LineItemQuotaBinding

                boq_count = ctx.db.query(BoqItem.id).filter(
                    BoqItem.project_id == ctx.project_id
                ).count()
                if boq_count > 0:
                    bound_count = ctx.db.query(LineItemQuotaBinding.id).join(
                        BoqItem, BoqItem.id == LineItemQuotaBinding.boq_item_id
                    ).filter(BoqItem.project_id == ctx.project_id).count()
                    parts.append(
                        f"\n📊 当前状态: {boq_count} 条清单项, {bound_count} 条已绑定, "
                        f"{boq_count - bound_count} 条未绑定"
                    )
                    if boq_count == bound_count and boq_count > 0:
                        parts.append("⚡ 所有项已绑定，可跳过阶段1和阶段2，直接从阶段3开始")
                    elif bound_count > 0:
                        parts.append(f"⚡ 阶段1可跳过（已有清单），阶段2只需处理 {boq_count - bound_count} 条未绑定项")
                    else:
                        parts.append("⚡ 阶段1可跳过（已有清单），阶段2需处理全部未绑定项")
                else:
                    parts.append("\n📊 该项目暂无清单项，需要从阶段1开始")
            except Exception:
                pass
        return "\n".join(parts)

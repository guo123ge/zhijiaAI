# Claude Code 架构深度分析与造价 Agent 改进方案

> 基于 claude-code-main (CCB v3 反编译源码) 的逐模块研究，对比当前 building-cost 框架，提出可落地的改进方案。

---

## 一、Claude Code 核心架构概览

```
┌─────────────────────────────────────────────────────────┐
│  QueryEngine (会话引擎)                                  │
│  ├─ 管理对话状态、历史快照、自动压缩                       │
│  └─ 驱动 query() 主循环                                  │
├─────────────────────────────────────────────────────────┤
│  query() (主循环 - 1700 行)                              │
│  ├─ 调用 Claude API (流式)                               │
│  ├─ 解析 tool_use → runTools()                           │
│  ├─ Token 预算 + 自动压缩                                │
│  └─ 记录 cost-tracker                                    │
├─────────────────────────────────────────────────────────┤
│  Tool Orchestration (工具编排层)                          │
│  ├─ partitionToolCalls() — 按 concurrency 分区           │
│  ├─ StreamingToolExecutor — 流式中就开始执行工具          │
│  └─ runToolsConcurrently() / runToolsSerially()          │
├─────────────────────────────────────────────────────────┤
│  Tool Registry (50+ 工具)                                │
│  ├─ 每个 Tool: name, inputSchema(Zod), call(),           │
│  │   checkPermissions(), isReadOnly(), isDestructive(),   │
│  │   isConcurrencySafe(), maxResultSizeChars              │
│  └─ buildTool() 填充默认值                               │
├─────────────────────────────────────────────────────────┤
│  AgentTool (Agent-as-Tool 子代理)                        │
│  ├─ 内置 Agent: Explore, Plan, Verification, General     │
│  ├─ 自定义 Agent: YAML/Markdown frontmatter 配置         │
│  ├─ Fork/Background/Remote 三种执行模式                   │
│  └─ Agent Memory + Agent Memory Snapshot                 │
├─────────────────────────────────────────────────────────┤
│  Skills / Hooks / Permissions                            │
│  ├─ Skills: 可注册的指令模板 (bundled + user-defined)     │
│  ├─ Hooks: pre/post tool use 拦截器                      │
│  └─ Permissions: allow/deny/ask 三级权限门控              │
└─────────────────────────────────────────────────────────┘
```

---

## 二、7 个核心设计模式深度解析

### 模式 1: Tool Concurrency Partition (工具并发分区)

**Claude Code 实现** (`toolOrchestration.ts`):
```typescript
function partitionToolCalls(toolUseMessages, toolUseContext): Batch[] {
  // 连续的 concurrency-safe 工具 → 一个并发 batch
  // 非安全工具 → 单独的串行 batch
  return toolUseMessages.reduce((acc, toolUse) => {
    const isConcurrencySafe = tool?.isConcurrencySafe(parsedInput.data)
    if (isConcurrencySafe && acc[last]?.isConcurrencySafe) {
      acc[last].blocks.push(toolUse)  // 合并到并发批次
    } else {
      acc.push({ isConcurrencySafe, blocks: [toolUse] })
    }
  }, [])
}
```

**当前框架差距**: 我们的 `base_agent.py` **串行执行**所有工具调用，没有利用 `ToolDef.is_concurrency_safe` 标志。

**改进方案**: 在 `BaseAgent.run()` 的工具执行段加入并发执行：
```python
# 按 concurrency 分区
batches = reg.partition_by_concurrency([tc["name"] for tc in tool_calls])
for is_concurrent, batch_names in batches:
    if is_concurrent and len(batch_names) > 1:
        with ThreadPoolExecutor(max_workers=min(len(batch_names), 5)) as pool:
            futures = {pool.submit(reg.execute, name, args, ctx): (name, args) ...}
            for f in as_completed(futures): ...
    else:
        # 串行执行
```

**价值**: 造价场景中 `search_quotas` + `get_project_info` + `get_boq_items` 都是只读工具，可并发执行，响应速度提升 2-3x。

---

### 模式 2: Streaming Tool Executor (流式工具执行器)

**Claude Code 实现** (`StreamingToolExecutor.ts`):
- API 还在流式返回 token 时就开始执行已解析的工具
- 工具结果按接收顺序缓冲，按发送顺序输出
- 子进程中 Bash 错误可通过 `siblingAbortController` 级联取消

**当前框架差距**: 我们必须等 LLM 完整响应后才开始工具执行。

**改进方案 (Phase F)**:
```python
class StreamingToolExecutor:
    """在流式响应中解析到 tool_use 后立即开始执行"""
    def __init__(self, registry, ctx): ...
    def on_tool_parsed(self, tool_call): ...  # 立即提交执行
    async def get_results_in_order(self): ...  # 按顺序返回结果
```

---

### 模式 3: Agent-as-Configuration (YAML/Markdown 配置化 Agent)

**Claude Code 实现** (`loadAgentsDir.ts`):
```yaml
# .claude/agents/pricing-expert.md
---
description: "定价专家 Agent"
tools: [search_quotas, bind_quota, get_cost_breakdown]
disallowedTools: [delete_project]
model: sonnet
maxTurns: 15
permissionMode: plan
mcpServers: [pricing-db]
hooks:
  PostToolUse:
    - matcher: "bind_quota"
      command: "echo Quota bound: $TOOL_INPUT"
memory: project
---

你是一位专业的工程计价AI助手，擅长...
```

**当前框架差距**: Agent 定义硬编码在 Python 类中 (`BoqAgentV2`, `QuotaMatchAgentV2` 等)，修改 prompt 或工具列表需要改代码、重启。

**改进方案**: 支持 Markdown/YAML frontmatter 定义 Agent：
```python
@dataclass
class AgentDefinition:
    agent_type: str
    description: str
    system_prompt: str
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    model: str | None = None
    max_turns: int = 12
    read_only: bool = False  # Explore/Plan 模式

def load_agents_from_dir(agents_dir: Path) -> list[AgentDefinition]:
    """从 .agents/ 目录加载 Markdown Agent 配置"""
```

**价值**: 
- 造价顾问可自定义 Agent prompt 而无需改代码
- 支持不同项目类型(住宅/商业/基建)加载不同 Agent 配置
- A/B 测试不同 prompt 策略

---

### 模式 4: Built-in Agent Types (内置 Agent 类型分化)

**Claude Code 内置 4 种 Agent**:

| Agent | 用途 | 特点 |
|-------|------|------|
| **Explore** | 只读搜索 | 禁止写文件、用 haiku 模型、跳过 CLAUDE.md |
| **Plan** | 架构规划 | 只读、分析后输出步骤方案 |
| **Verification** | 对抗性验证 | 运行命令验证实现、不允许修改项目 |
| **General** | 通用执行 | 全权限、默认模型 |

**造价场景映射**:

| 造价 Agent | 对应模式 | 用途 |
|-----------|---------|------|
| **ExploreAgent** | Explore | 只读查询：搜定额、查市场价、查历史项目 |
| **PlanAgent** | Plan | 组价方案设计：分析清单项、推荐定额组合策略 |
| **ValidationAgent** | Verification | 对抗性审核：检查绑定合理性、单价异常、漏项 |
| **ExecuteAgent** | General | 执行操作：绑定定额、修改单价、批量处理 |

**关键差异**:
- Explore Agent 使用 `haiku` (便宜/快速模型)，节省成本
- Plan Agent 是只读的，产出方案但不执行
- Verification Agent 故意"试图打破"结果，而不是确认它正确

**改进方案**: 为造价 Agent 引入 `read_only` 标志：
```python
class CostExploreAgent(BaseAgent):
    name = "cost_explore"
    read_only = True  # 框架自动过滤写操作工具
    model_tier = "fast"  # ModelRouter 使用快速模型
    omit_project_context = True  # 节省 token

class CostValidationAgent(BaseAgent):
    name = "cost_validation"
    read_only = True
    system_prompt = """你是一个对抗性审核专家。你的目标不是确认结果正确，
    而是尽力找出问题..."""
```

---

### 模式 5: Hook System (前置/后置拦截器)

**Claude Code 实现** (`toolHooks.ts`):
```
PreToolUse hook → 权限检查 → 工具执行 → PostToolUse hook
```

- **PreToolUse**: 在工具执行前拦截，可修改输入或阻止执行
- **PostToolUse**: 在工具执行后拦截，可修改输出或触发副作用

**造价场景应用**:
```python
@pre_tool_hook("bind_quota")
def validate_quota_binding(ctx, tool_input):
    """绑定定额前自动检查：清单项是否已有绑定"""
    existing = get_existing_binding(ctx.db, tool_input["boq_item_id"])
    if existing:
        return HookResult(
            action="ask_user",
            message=f"清单项已绑定定额 {existing.code}，是否替换？"
        )

@post_tool_hook("bind_quota")
def auto_recalculate(ctx, tool_input, tool_output):
    """绑定定额后自动重新计算综合单价"""
    recalculate_composite_rate(ctx.db, tool_input["boq_item_id"])
    return HookResult(action="continue", message="已自动重算综合单价")
```

**改进方案**: 在 `ToolDef` 中增加 hook 支持：
```python
@dataclass
class ToolDef:
    # ... existing fields ...
    pre_hooks: list[Callable] = field(default_factory=list)
    post_hooks: list[Callable] = field(default_factory=list)
    
    def execute(self, ctx, args):
        # Run pre-hooks
        for hook in self.pre_hooks:
            result = hook(ctx, args)
            if result and result.action == "block":
                return result.message
        # Execute tool
        output = self.func(ctx, **args)
        # Run post-hooks
        for hook in self.post_hooks:
            hook(ctx, args, output)
        return output
```

---

### 模式 6: Context Injection (上下文注入)

**Claude Code 实现** (`context.ts`):
- 每个对话开始时注入：git status、CLAUDE.md、日期
- ToolUseContext 携带完整运行时上下文传递给每个工具
- Agent Memory 跨会话持久化

**当前框架差距**: `AgentContext` 只有 `db`, `project_id`, `user_id`, `budget`。缺少领域上下文。

**改进方案**: 丰富 AgentContext：
```python
@dataclass
class AgentContext:
    db: Session
    project_id: int
    user_id: int | None = None
    budget: TokenBudget | None = None
    
    # ── 新增：领域上下文 ──
    project_summary: str | None = None      # 项目基本信息摘要
    pricing_rules: str | None = None        # 当前计价规则摘要
    recent_operations: list[str] | None = None  # 最近操作历史
    memory: dict[str, Any] | None = None    # Agent 跨会话记忆
    
    def inject_project_context(self):
        """自动加载项目上下文，注入到 system prompt"""
        project = self.db.query(Project).get(self.project_id)
        self.project_summary = f"""
项目: {project.name}
类型: {project.project_type}
地区: {project.region}
清单项数: {project.boq_count}
已绑定率: {project.binding_rate}%
"""
```

---

### 模式 7: Auto-Compaction (自动对话压缩)

**Claude Code 实现** (`services/compact/`):
- 当对话 token 接近上下文窗口限制时自动压缩
- 保留最近 N 条消息 + 压缩摘要
- 三种模式：auto-compact、micro-compact、API compact

**造价场景问题**: 大型项目审查可能产生数十轮对话，token 消耗巨大。

**改进方案**: 在 BaseAgent 中加入压缩机制：
```python
def _maybe_compact_messages(self, messages, budget):
    """当消息 token 数超过阈值时自动压缩"""
    if budget.total_input_tokens > budget.compact_threshold:
        # 保留 system + 最近 4 条 + 压缩摘要
        summary = self._summarize_old_messages(messages[2:-4])
        return [messages[0], {"role": "user", "content": summary}] + messages[-4:]
    return messages
```

---

## 三、造价专用 Agent 具体改进优先级

### Phase F: 核心框架增强 (建议优先)

| # | 改进项 | 工作量 | 价值 | 来源模式 |
|---|--------|--------|------|---------|
| F1 | 工具并发执行 | 中 | **高** — 只读工具并行，响应提速 2-3x | 模式 1 |
| F2 | Agent 只读模式 | 小 | **高** — Explore/Plan Agent 自动过滤写工具 | 模式 4 |
| F3 | ToolDef Hook 系统 | 中 | **高** — 绑定后自动重算、操作前确认 | 模式 5 |
| F4 | AgentContext 领域上下文注入 | 小 | **中** — 项目信息自动注入 prompt | 模式 6 |
| F5 | 对话自动压缩 | 中 | **中** — 大项目审查不超 token 限制 | 模式 7 |

### Phase G: 造价专用 Agent 类型

| # | Agent 类型 | 用途 | 工具子集 |
|---|-----------|------|---------|
| G1 | CostExploreAgent | 只读快速搜索 | search_quotas, get_project_info, get_boq_items |
| G2 | CostPlanAgent | 组价方案设计 | (Explore工具) + 分析类工具 |
| G3 | CostValidationAgent | 对抗性审核 | 全部只读工具 + 验证工具 |
| G4 | CostExecuteAgent | 执行绑定/修改 | 全部工具 |

### Phase H: 高级功能

| # | 功能 | 来源 |
|---|------|------|
| H1 | Agent YAML 配置化 | 模式 3 |
| H2 | Streaming Tool Executor | 模式 2 |
| H3 | Agent Memory (跨会话记忆) | Claude Code `agentMemory.ts` |
| H4 | Skills 系统 (造价知识技能包) | Claude Code `skills/` |

---

## 四、与当前框架的逐项对比

| 特性 | Claude Code | 当前 building-cost | 差距 |
|------|------------|-------------------|------|
| 工具并发 | ✅ partitionToolCalls + 并行执行 | ❌ 全串行 | **大** |
| 流式工具执行 | ✅ StreamingToolExecutor | ❌ 等完整响应 | 中 |
| 工具元数据 | ✅ isReadOnly/isDestructive/concurrencySafe/maxResultSize | ✅ read_only/destructive/concurrency_safe | 小 |
| Agent 配置化 | ✅ YAML frontmatter | ❌ 硬编码 Python 类 | **大** |
| 内置 Agent 分化 | ✅ Explore/Plan/Verification/General | ⚠️ 有类型但无只读/对抗模式 | 中 |
| Hook 系统 | ✅ pre/post tool use | ❌ 无 | **大** |
| 上下文注入 | ✅ git status + CLAUDE.md + date | ⚠️ 仅 db/project_id | 中 |
| 对话压缩 | ✅ auto/micro/API compact | ❌ 无 | 中 |
| 成本追踪 | ✅ cost-tracker.ts 详细到模型 | ✅ TraceCollector + cost dashboard | 小 |
| Agent-as-Tool | ✅ 子代理递归调用 | ✅ agent_as_tool.py | 已实现 |
| Pipeline | ❌ (概念层面有 query chain) | ✅ pipeline.py 多阶段 | 我们更好 |
| 权限系统 | ✅ 6300 行完整权限 | ❌ 无 (不需要，非 CLI) | N/A |
| Skills 系统 | ✅ bundled + user-defined | ❌ 无 | 中 |

---

## 五、实施路线图

```
当前 ──────── Phase F (核心增强) ──────── Phase G (造价Agent) ──────── Phase H (高级)
已完成:        F1 并发执行 (1天)          G1 CostExplore (0.5天)      H1 YAML配置 (2天)
A-E 框架       F2 只读模式 (0.5天)        G2 CostPlan (0.5天)         H2 流式执行 (2天)
前端 UI        F3 Hook 系统 (1天)         G3 CostValidation (1天)     H3 Agent 记忆 (1天)
               F4 上下文注入 (0.5天)      G4 CostExecute (0.5天)      H4 Skills系统 (2天)
               F5 对话压缩 (1天)
               ──────────────
               总计 ~4天                   总计 ~2.5天                  总计 ~7天
```

---

## 六、总结

Claude Code 最有价值的 7 个可借鉴模式中，**3 个已在我们框架中实现** (Tool 元数据、Agent-as-Tool、Pipeline)，**4 个值得引入** (工具并发、Hook 系统、Agent 配置化、内置类型分化)。

最高 ROI 的改进：
1. **F1 工具并发执行** — 改动小 (改 base_agent.py ~30 行)，性能提升大
2. **F2 Agent 只读模式** — 自动过滤，配合 ModelRouter 省钱
3. **F3 Hook 系统** — 造价业务流程自动化的基础 (绑定→重算→校验)

这些改进将把我们的框架从"能用"提升到"专业级造价 Agent 系统"。

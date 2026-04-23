# AI Agent 架构升级方案

> 基于行业最佳实践（Microsoft Azure Agent Patterns, LangGraph, OpenAI Tool Calling）  
> 对标 PRD 定位：**AI 原生工程计价软件**

---

## 1. 现状诊断

### 1.1 已有 Agent（9 个）

| Agent | 职责 | Tool Calling | SSE 流式 |
|-------|------|:---:|:---:|
| `valuation_agent` | 智能组价（搜索定额→绑定→计算） | ✅ 8 tools | ✅ |
| `validation_agent` | 数据审核（编码合规/异常检测） | ✅ 5 tools | ✅ |
| `chat_agent` | 项目问答（带上下文工具调用） | ✅ 4 tools | ❌ |
| `boq_agent` | 清单生成 | ❌ prompt only | ❌ |
| `query_agent` | 自然语言查询 | ❌ prompt only | ❌ |
| `insight_agent` | 数据洞察 | ❌ prompt only | ❌ |
| `quota_match_agent` | 定额匹配推荐 | ❌ prompt only | ❌ |
| `batch_review_agent` | 批量审核 | ❌ prompt only | ❌ |
| `rate_suggestion_agent` | 费率建议 | ❌ prompt only | ❌ |

### 1.2 现有架构问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | **无编排层（Orchestrator）** | 每个 Agent 独立运行，无法协作完成复杂任务（如"导入清单→匹配定额→组价→校验"端到端流程） |
| 2 | **大量重复代码** | `AgentStep`、tool dispatcher、agent loop 在 3 个 Agent 中复制粘贴 |
| 3 | **无 Agent 注册表** | Agent 硬编码在路由中，无法动态发现或组合 |
| 4 | **无统一状态管理** | 每个 Agent 各自管理消息历史，无跨 Agent 状态传递 |
| 5 | **无成本控制** | 没有 token 预算、模型路由、结果缓存 |
| 6 | **可观测性不足** | 仅 `log_ai_call` 记录调用，无结构化 Agent trace 持久化到 DB |
| 7 | **无人工审批门** | 高风险操作（绑定定额、修改组价）无 Human-in-the-Loop 机制 |
| 8 | **6 个 Agent 无 Tool Calling** | 仅用 prompt→text，无法执行操作，违背 Agent 定义 |

---

## 2. 目标架构

### 2.1 分层架构

```
┌─────────────────────────────────────────────────┐
│                   前端 UI Layer                    │
│  ProjectList │ ProjectDetail │ AiPanel │ Chat     │
└────────────────────┬────────────────────────────┘
                     │ SSE / REST
┌────────────────────┴────────────────────────────┐
│              API Gateway (FastAPI)               │
│  /agent/orchestrate  /agent/stream  /agent/tasks │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────┐
│           Orchestrator (Supervisor Agent)         │
│  ┌─────────────────────────────────────────────┐ │
│  │  Intent Router → Agent Selector → Executor  │ │
│  │  State Machine │ Context Manager │ Budget    │ │
│  └─────────────────────────────────────────────┘ │
└────────┬───────┬───────┬───────┬───────┬────────┘
         │       │       │       │       │
    ┌────┴──┐ ┌──┴───┐ ┌┴────┐ ┌┴────┐ ┌┴─────┐
    │Valuat.│ │Valid. │ │BOQ  │ │Query│ │Report│
    │Agent  │ │Agent  │ │Agent│ │Agent│ │Agent │
    └───┬───┘ └──┬───┘ └─┬───┘ └─┬───┘ └──┬───┘
        │        │       │       │        │
   ┌────┴────────┴───────┴───────┴────────┴───┐
   │         Shared Tool Registry (MCP-like)   │
   │  search_quotas │ bind_quota │ calculate   │
   │  validate │ search_codes │ get_prices     │
   │  query_boq │ export │ create_snapshot      │
   └──────────────────┬───────────────────────┘
                      │
   ┌──────────────────┴───────────────────────┐
   │         Data Layer (SQLAlchemy + DB)       │
   │  Projects │ BOQ │ Quotas │ Bindings │ ...  │
   └───────────────────────────────────────────┘
```

### 2.2 核心设计原则

| 原则 | 说明 | 来源 |
|------|------|------|
| **Supervisor Pattern** | 一个编排 Agent 接收用户意图，分派给专业 Agent | Microsoft Azure Patterns |
| **State Machine** | Agent 执行流建模为有限状态机，非自由循环 | LangGraph / Best Practices |
| **Shared Tool Registry** | 所有工具统一注册，Agent 按权限使用子集 | MCP / Tool Design Principles |
| **Atomic Tools** | 工具做单一操作，返回详细错误信息 | Production Best Practices |
| **Context Injection** | project_id/db 等由运行时注入，不让 LLM 提供 | Tool Design Anti-pattern |
| **Human-in-the-Loop** | 高风险操作暂停等待前端确认 | Azure HITL Pattern |
| **Structured Observability** | 每个 AgentStep 写入 `agent_traces` 表 | Production Observability |
| **Token Budget** | 每次 Agent 运行有 token 上限和最大步数 | Cost Control |

---

## 3. 实施路径（5 个 Phase）

### Phase A: 基础设施层（Agent Framework）

**目标：消除重复代码，建立统一 Agent 运行时**

```
backend/app/ai/
├── framework/
│   ├── __init__.py
│   ├── base_agent.py        # BaseAgent 抽象类（统一 loop + step tracking）
│   ├── state.py             # AgentState 状态机（messages, steps, budget）
│   ├── tool_registry.py     # 全局工具注册表（name → function + schema）
│   ├── context.py           # AgentContext（db, project_id, user_id 等注入）
│   ├── orchestrator.py      # Supervisor Orchestrator
│   └── budget.py            # TokenBudget（max_tokens, max_turns, cost tracking）
├── agents/                  # 各专业 Agent（继承 BaseAgent）
├── tools/                   # 工具实现（从 agents 中抽离）
│   ├── quota_tools.py
│   ├── validation_tools.py
│   ├── boq_tools.py
│   ├── pricing_tools.py
│   └── export_tools.py
├── providers/               # 不变
├── prompts/                 # 不变
└── config.py                # 不变
```

关键代码设计：

```python
# base_agent.py
class BaseAgent(ABC):
    name: str
    description: str              # 供 Orchestrator 选择用
    tools: list[ToolDef]          # 从 registry 中选取子集
    system_prompt: str
    max_turns: int = 10
    
    def run(self, ctx: AgentContext, instruction: str) -> AgentResult:
        """统一的 agent loop，子类只需定义 tools 和 prompt"""
        
    @abstractmethod
    def get_tools(self, registry: ToolRegistry) -> list[ToolDef]:
        """每个 Agent 声明自己需要的工具子集"""

# tool_registry.py  
class ToolRegistry:
    _tools: dict[str, ToolDef]
    
    def register(self, name, func, schema, description): ...
    def get(self, name) -> ToolDef: ...
    def get_openai_schemas(self, names: list[str]) -> list[dict]: ...
    def execute(self, name, args, ctx: AgentContext) -> str: ...

# orchestrator.py
class Orchestrator:
    agents: dict[str, BaseAgent]
    
    def route(self, user_intent: str) -> str:
        """确定性路由 or LLM 路由到具体 Agent"""
        
    def run(self, ctx: AgentContext, message: str) -> AgentResult:
        """接收用户消息 → 路由 → 执行 → 返回"""
        
    def run_pipeline(self, ctx: AgentContext, steps: list[PipelineStep]):
        """Sequential orchestration: 多 Agent 串行执行"""
```

### Phase B: 工具抽离 + Agent 迁移

**目标：将现有 3 个 tool-calling agent 迁移到新框架**

1. 从 `valuation_agent.py` 抽出 8 个工具 → `tools/quota_tools.py` + `tools/pricing_tools.py`
2. 从 `validation_agent.py` 抽出 5 个工具 → `tools/validation_tools.py`
3. 从 `chat_agent.py` 抽出 4 个工具 → `tools/boq_tools.py`
4. 每个 Agent 改为继承 `BaseAgent`，只定义 `name`, `description`, `system_prompt`, `get_tools()`
5. 注册到 `AgentRegistry`

### Phase C: 升级无工具 Agent → Tool-Calling Agent

**目标：将 6 个 prompt-only agent 升级为真正的 Agent**

| Agent | 新增 Tools |
|-------|-----------|
| `boq_agent` | `create_boq_item`, `update_boq_item`, `search_standard_codes`, `import_excel_preview` |
| `query_agent` | `query_boq_items`, `query_bindings`, `query_prices`, `get_project_stats` |
| `insight_agent` | `get_project_stats`, `compare_versions`, `detect_anomalies`, `get_cost_breakdown` |
| `quota_match_agent` | `search_quotas`, `get_quota_detail`, `search_standard_codes`, `bind_quota` |
| `batch_review_agent` | `run_full_validation`, `list_unbound_items`, `batch_bind_quotas` |
| `rate_suggestion_agent` | `get_fee_config`, `get_regional_rates`, `suggest_rates` |

### Phase D: Orchestrator + Pipeline

**目标：实现 Supervisor 编排和端到端工作流**

关键工作流（PRD 对应）：

```
Pipeline: "导入清单 → 产出第一版可复核组价成果"

Step 1: BOQ Agent      → 解析上传文件，生成清单项
Step 2: Match Agent    → 为每个清单项推荐定额候选
Step 3: Valuation Agent → 批量确认并计算组价
Step 4: Validation Agent → 全面校验，输出问题清单
Step 5: Report Agent   → 生成汇总报告

[Human Gate] → 用户确认/修改 → 继续下一步
```

前端交互：
- 新增 `/agent/orchestrate` SSE 端点，流式推送各 Agent 步骤
- 前端 `AiPanel` 展示多 Agent 协作过程（thinking → tool_call → result → handoff）
- 高风险步骤弹出确认对话框（Human-in-the-Loop）

### Phase E: 可观测性 + 成本控制

1. **Agent Trace 表**（`agent_traces`）
   - `id`, `project_id`, `session_id`, `agent_name`, `step_type`, `content`, `tool_name`, `tool_args`, `tool_result`, `token_count`, `duration_ms`, `created_at`
   
2. **Token Budget**
   - 每次 Agent 运行设置 max_tokens（按模型定价）
   - 超预算自动 force-answer
   
3. **Model Routing**
   - 简单任务（query, insight）→ 小模型（deepseek-chat / qwen-turbo）
   - 复杂任务（valuation, validation）→ 大模型（deepseek-reasoner / qwen-max）
   
4. **Tool Result 缓存**
   - 同一 session 内相同工具+参数的结果缓存

---

## 4. 优先级排序

| Phase | 预估工作量 | 价值 | 建议优先级 |
|-------|-----------|------|-----------|
| **A: Framework** | 2-3 天 | 消除重复，后续所有升级的基础 | **P0 立即做** |
| **B: Agent 迁移** | 1-2 天 | 现有 3 个 Agent 迁移到新框架 | **P0 紧随 A** |
| **C: 升级无工具 Agent** | 3-4 天 | 6 个 Agent 获得真正能力 | **P1** |
| **D: Orchestrator** | 3-4 天 | 实现端到端 AI 工作流 | **P1** |
| **E: 可观测性+成本** | 1-2 天 | 生产就绪 | **P1** |

**总计：约 10-15 天**，建议按 A → B → C → D → E 顺序迭代。

---

## 5. 与 PRD 的对照

| PRD 要求 | 当前状态 | 升级后 |
|----------|---------|--------|
| AI Copilot（解析/匹配/解释/风险） | 部分实现（3 个 Agent） | 全部 Agent 升级 + Orchestrator 编排 |
| 证据链追溯 | Provenance API 已有 | Agent trace 表增强可审计性 |
| AI Guardrails（无来源不编数） | System prompt 约束 | Tool + State Machine 强制校验 |
| AI 输出可回放 | 仅 SSE 流式 | Agent trace 持久化 + 完整重放 |
| 批量确认/回滚 | 手动 | Orchestrator pipeline + HITL |
| 问答式导航 | query_agent(prompt only) | query_agent + DB tools |
| 差异解释 | insight_agent(prompt only) | insight_agent + compare tools |

---

## 6. Claude Code Agent 架构深度分析

> 基于对 `claude-code-main` 源码的完整逆向分析

### 6.1 架构总览

Claude Code 的 Agent 系统是一个**生产级多层 Agent 编排框架**，核心分为 5 层：

```
┌─────────────────────────────────────────────────────┐
│  QueryEngine (会话级编排器)                            │
│  管理对话状态、compaction、file history、attribution    │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────┐
│  query() 函数 (核心 Agent Loop)                       │
│  while(true): 调用 API → 处理 tool_use → 执行工具     │
│  → 追加结果 → 继续循环 (直到无 tool_calls)             │
│  内含: auto-compact / token budget / error recovery    │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────┐
│  Tool Orchestration (工具执行层)                       │
│  partitionToolCalls → 并发安全的并行执行                │
│  非并发安全的串行执行 → context modifier 传递           │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────┐
│  Tool Registry (50+ 工具)                             │
│  每个工具: name / inputSchema(Zod) / call() / prompt() │
│  / checkPermissions() / isReadOnly() / isDestructive() │
│  buildTool() 统一构造，填充默认值                       │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────┐
│  AgentTool (子 Agent 即工具)                           │
│  Agent 本身是一个 Tool，可被父 Agent 像调用工具一样调用   │
│  支持: 同步/异步/前台/后台/隔离 worktree               │
└─────────────────────────────────────────────────────┘
```

### 6.2 关键设计模式（可借鉴）

#### 模式 1: Tool 即一等公民（Tool as First-Class Citizen）

```typescript
// Claude Code 的 Tool 类型定义（简化）
type Tool = {
  name: string
  inputSchema: ZodSchema          // 强类型输入验证
  call(args, context): ToolResult // 执行逻辑
  description(input): string      // 动态描述
  checkPermissions(input, ctx)    // 权限检查
  isReadOnly(input): boolean      // 是否只读
  isDestructive(input): boolean   // 是否破坏性
  isConcurrencySafe(input): bool  // 是否可并发
  maxResultSizeChars: number      // 结果大小限制
  validateInput(input, ctx)       // 输入验证
}
```

**可借鉴**: 每个工具自带权限、并发安全性、破坏性标记。我们的工具目前只有 name + function，缺少这些元数据。

#### 模式 2: Agent 即 Tool（Agent-as-Tool Pattern）

Claude Code 最核心的设计：**AgentTool 是一个 Tool**，主 Agent 可以像调用工具一样调用子 Agent。

```typescript
// AgentTool 的 inputSchema
z.object({
  description: z.string(),        // 任务描述
  prompt: z.string(),             // 任务指令
  subagent_type: z.string(),      // Agent 类型选择
  model: z.enum(['sonnet', 'opus', 'haiku']),  // 模型选择
  run_in_background: z.boolean(), // 前台/后台
})
```

**子 Agent 类型**:
- `general-purpose`: 通用 Agent（tools: ['*']，可用所有工具）
- `Explore`: 只读搜索 Agent（禁用编辑工具，用小模型 haiku）
- `Plan`: 规划 Agent（只读 + 规划）
- `Verification`: 验证 Agent

**可借鉴**: 我们的 Orchestrator 可以把每个专业 Agent 包装成一个 Tool，让 Supervisor Agent 通过 tool_call 来调度子 Agent。

#### 模式 3: 工具并发执行分区（Tool Concurrency Partition）

```typescript
// 根据工具的 isConcurrencySafe 属性分批
function partitionToolCalls(toolUseMessages, context): Batch[] {
  // 连续的只读工具 → 合为一批并行执行
  // 非只读工具 → 单独一批串行执行
}

// 并行: 多个 grep/read 同时执行
// 串行: write/delete 必须按序
```

**可借鉴**: 我们的 `_execute_tool` 是完全串行的。搜索定额、查询价格等只读工具可以并行执行，大幅提速。

#### 模式 4: Agent 定义即配置（Agent-as-Configuration）

Claude Code 支持通过 **Markdown frontmatter** 定义自定义 Agent：

```yaml
---
name: my-agent
description: When to use this agent
tools: [Bash, FileRead, GrepTool]
disallowedTools: [FileWrite]
model: haiku
permissionMode: plan
maxTurns: 20
background: true
memory: project
---

You are a specialist agent for...
(system prompt in markdown body)
```

**可借鉴**: 我们可以用 YAML/JSON 配置文件定义 Agent，而不是硬编码 Python 类。这样业务人员也能调整 Agent 行为。

#### 模式 5: 上下文注入（Context Injection via ToolUseContext）

```typescript
type ToolUseContext = {
  options: { tools, model, commands, debug, ... }
  abortController: AbortController
  readFileState: FileStateCache
  getAppState(): AppState
  setAppState(f): void
  messages: Message[]
  agentId?: AgentId
  // ... 30+ 字段
}
```

所有工具通过 `ToolUseContext` 获取运行时上下文，**工具永远不需要 LLM 提供** project_id、session_id 等信息。

**可借鉴**: 我们现在的 `_execute_tool(tool_name, tool_args, db, boq, project_region)` 参数列表很长，应该封装为 `AgentContext`。

#### 模式 6: 自动压缩（Auto-Compaction）

Claude Code 在 `query()` 循环中自动处理上下文窗口：
- **Auto-compact**: 上下文超过阈值时自动总结历史
- **Snip-compact**: 裁剪中间的长工具输出
- **Micro-compact**: 细粒度压缩单条消息
- **Tool result budget**: 工具结果超大时自动持久化到文件

**可借鉴**: 我们的 Agent 循环没有任何上下文管理，长任务会超出模型窗口限制。

#### 模式 7: 权限与安全门（Permission Gates）

```typescript
// 每个工具调用前检查权限
const permissionResult = await tool.checkPermissions(input, context)
// permissionResult: { behavior: 'allow' | 'deny' | 'ask' }

// 破坏性操作需要用户确认
if (tool.isDestructive(input)) {
  // 弹出确认 UI，等待用户审批
}
```

**可借鉴**: 直接对应我们 PRD 中的 Human-in-the-Loop 需求。绑定定额、修改组价应该需要确认。

### 6.3 与我们系统的映射关系

| Claude Code 概念 | 对应到我们的系统 |
|-----------------|----------------|
| `QueryEngine` | **Orchestrator** — 管理整个 AI 会话 |
| `query()` loop | **BaseAgent.run()** — 统一 Agent 循环 |
| `Tool` 类型 | **ToolDef** — 带元数据的工具定义 |
| `AgentTool` | **子 Agent 调度** — Supervisor 调用专业 Agent |
| `ToolUseContext` | **AgentContext** — 运行时上下文注入 |
| `buildTool()` | **ToolRegistry.register()** — 统一工具构造 |
| `partitionToolCalls` | **并行工具执行** — 只读工具并发 |
| `AgentDefinition` (YAML) | **Agent 配置化** — 非硬编码 Agent |
| `checkPermissions` | **HITL 审批门** — 高风险操作确认 |
| `auto-compact` | **上下文管理** — 长会话压缩 |
| `AgentStep` tracking | **agent_traces 表** — 结构化可观测性 |

### 6.4 不适用的部分

| Claude Code 特有 | 原因 |
|-----------------|------|
| Ink (Terminal UI) | 我们是 Web UI，用 React + Ant Design |
| Git worktree isolation | 我们不操作文件系统 |
| Bash/FileEdit 工具 | 我们的工具是 DB 操作，非文件操作 |
| MCP 协议 | 暂不需要外部工具扩展 |
| Feature flags (GrowthBook) | 我们用更简单的 env var 配置 |

---

## 7. 技术选型建议（更新后）

| 组件 | 推荐方案 | 理由 | Claude Code 参考 |
|------|---------|------|-----------------|
| Agent Framework | **自建轻量框架** | 系统已有 Provider 抽象层 | 借鉴 Tool 类型 + buildTool 模式 |
| Tool 定义 | **带元数据的 ToolDef** | 支持权限/并发/破坏性标记 | 对标 Claude Code Tool 类型 |
| Agent 定义 | **YAML 配置 + Python 类** | 灵活性 + 类型安全 | 对标 AgentDefinition |
| Agent 调度 | **Agent-as-Tool 模式** | Supervisor 用 tool_call 调度子 Agent | 对标 AgentTool |
| 工具执行 | **并发分区执行** | 只读工具并行，写工具串行 | 对标 partitionToolCalls |
| 上下文 | **AgentContext dataclass** | 统一注入，不让 LLM 提供 | 对标 ToolUseContext |
| State Machine | **Python dataclass + enum** | 简单可靠 | - |
| Tool Protocol | **OpenAI Function Calling** | 已有实现 | - |
| Observability | **agent_traces 表** | 与审计日志一致 | - |
| SSE Streaming | **保持现有模式** | 已验证可用 | - |

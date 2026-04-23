"""Agent Framework — unified infrastructure for all AI agents.

Provides:
- ToolDef / ToolRegistry: typed tool definitions with metadata
- AgentContext: runtime context injection (db, project_id, etc.)
- BaseAgent: abstract agent with unified reasoning loop
- TokenBudget: cost control per agent run
- agent_to_tool: wrap any BaseAgent as a ToolDef (Agent-as-Tool pattern)
- Pipeline: sequential multi-agent workflow execution
- TraceCollector: automatic observability and cost tracking
- ModelRouter: task-based model tier selection
"""

from app.ai.framework.types import AgentStep, AgentResult, StepType
from app.ai.framework.tool_def import ToolDef, tool
from app.ai.framework.tool_registry import ToolRegistry
from app.ai.framework.context import AgentContext
from app.ai.framework.budget import TokenBudget
from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.agent_as_tool import agent_to_tool
from app.ai.framework.pipeline import Pipeline, Stage, PipelineResult
from app.ai.framework.trace_collector import TraceCollector
from app.ai.framework.model_router import route_model, ModelTier

__all__ = [
    "AgentStep",
    "AgentResult",
    "StepType",
    "ToolDef",
    "tool",
    "ToolRegistry",
    "AgentContext",
    "TokenBudget",
    "BaseAgent",
    "agent_to_tool",
    "Pipeline",
    "Stage",
    "PipelineResult",
    "TraceCollector",
    "route_model",
    "ModelTier",
]

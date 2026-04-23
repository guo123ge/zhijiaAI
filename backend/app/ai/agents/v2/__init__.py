"""V2 Agents — migrated to the BaseAgent framework.

These agents replace the hand-rolled loops in the original agent files.
The original files are preserved for backward compatibility during migration.
"""

from app.ai.agents.v2.valuation_agent_v2 import ValuationAgentV2
from app.ai.agents.v2.validation_agent_v2 import ValidationAgentV2
from app.ai.agents.v2.chat_agent_v2 import ChatAgentV2
from app.ai.agents.v2.boq_agent_v2 import BoqAgentV2
from app.ai.agents.v2.query_agent_v2 import QueryAgentV2
from app.ai.agents.v2.insight_agent_v2 import InsightAgentV2
from app.ai.agents.v2.quota_match_agent_v2 import QuotaMatchAgentV2
from app.ai.agents.v2.batch_review_agent_v2 import BatchReviewAgentV2
from app.ai.agents.v2.rate_suggestion_agent_v2 import RateSuggestionAgentV2

# Phase G: Specialized cost agents
from app.ai.agents.v2.cost_explore_agent import CostExploreAgent
from app.ai.agents.v2.cost_plan_agent import CostPlanAgent
from app.ai.agents.v2.cost_validation_agent import CostValidationAgent
from app.ai.agents.v2.cost_execute_agent import CostExecuteAgent

__all__ = [
    "ValuationAgentV2",
    "ValidationAgentV2",
    "ChatAgentV2",
    "BoqAgentV2",
    "QueryAgentV2",
    "InsightAgentV2",
    "QuotaMatchAgentV2",
    "BatchReviewAgentV2",
    "RateSuggestionAgentV2",
    # Phase G
    "CostExploreAgent",
    "CostPlanAgent",
    "CostValidationAgent",
    "CostExecuteAgent",
]

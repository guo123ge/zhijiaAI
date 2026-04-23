"""AI insight analysis endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.agents.insight_agent import VALID_CONTEXT_TYPES
from app.ai.agents.v2.insight_agent_v2 import InsightAgentV2
from app.ai.framework.context import AgentContext
from app.db.session import get_db
from app.schemas.ai_insight import AIAnalyzeRequest, AIAnalyzeResponse

router = APIRouter(tags=["ai"])


@router.post(
    "/projects/{project_id}/ai-analyze",
    response_model=AIAnalyzeResponse,
)
def ai_analyze(
    project_id: int,
    payload: AIAnalyzeRequest,
    db: Session = Depends(get_db),
) -> AIAnalyzeResponse:
    """Generate AI insight for the given project context (V2 — tool-calling)."""
    if payload.context_type not in VALID_CONTEXT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid context_type. Must be one of: {', '.join(sorted(VALID_CONTEXT_TYPES))}",
        )

    data = {**payload.context_data, "project_id": project_id}
    try:
        import app.ai.tools  # noqa: F401 — ensure tools registered

        ctx = AgentContext(
            db=db,
            project_id=project_id,
            metadata={"context_type": payload.context_type, "context_data": data},
        )
        agent = InsightAgentV2()
        result = agent.run(ctx, payload.context_data.get("question", ""))
        insight = result.answer if result.success else None
    except Exception:
        return AIAnalyzeResponse(insight=None, ai_available=False)

    return AIAnalyzeResponse(
        insight=insight,
        ai_available=insight is not None,
    )

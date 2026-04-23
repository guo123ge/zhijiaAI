"""Orchestrator & Pipeline API endpoints.

Provides:
- POST /projects/{id}/orchestrate — free-form task via Supervisor agent
- POST /projects/{id}/boq-items/{id}/pipeline/pricing — full pricing pipeline
- POST /projects/{id}/pipeline/audit — full project audit pipeline
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any, Generator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orchestrator"])


# ── Schemas ──────────────────────────────────────────────────────

class ConversationTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class OrchestrateRequest(BaseModel):
    instruction: str
    user_id: int | None = None
    #: Override AI_AUTO_SAVE_MEMORY env default for this single call.
    #: None = use env default; True/False = force on/off.
    auto_save_memory: bool | None = None
    #: Prior conversation turns. Enables multi-turn chat with the Orchestrator.
    conversation_history: list[ConversationTurn] = []


class OrchestrateResponse(BaseModel):
    answer: str
    tool_calls_made: int = 0
    error: str | None = None
    #: Phase H8: keys of memories auto-saved during this run (H7).
    auto_saved_memories: list[str] = []


class PipelineStageOut(BaseModel):
    index: int
    agent: str
    success: bool
    duration_s: float
    tool_calls: int
    answer: str = ""


class PipelineResponse(BaseModel):
    pipeline: str
    stages: list[PipelineStageOut]
    final_answer: str
    success: bool
    total_duration_s: float
    error: str | None = None


# ── Orchestrator endpoint ────────────────────────────────────────

# ── Phase H8: production-grade orchestrator builder ─────────────

def _resolve_auto_save(requested: bool | None) -> bool:
    """Request override > env default > False."""
    if requested is not None:
        return requested
    from app.ai.config import get_memory_settings
    return get_memory_settings().auto_save_memory_default


def _build_production_orchestrator(auto_save: bool):
    """Construct an OrchestratorAgent wired for production.

    - Always registers memory + skill tools (via OrchestratorAgent __init__).
    - Installs LLMMemoryExtractor when auto_save=True so successful runs
      auto-sediment key facts.
    """
    from app.ai.agents.v2.orchestrator import OrchestratorAgent

    agent = OrchestratorAgent()
    if auto_save:
        from app.ai.config import get_memory_settings
        from app.ai.framework.memory_extractor import LLMMemoryExtractor

        settings = get_memory_settings()
        agent.auto_save_memory = True
        agent.memory_extractor = LLMMemoryExtractor(
            max_items=settings.memory_extractor_max_items,
        )
    return agent


def _build_ctx_with_memory(db: Session, project_id: int, user_id: int | None):
    """Build AgentContext with SQLAlchemyMemoryStore attached."""
    from app.ai.framework.context import AgentContext
    from app.ai.framework.memory_store import SQLAlchemyMemoryStore

    return AgentContext(
        db=db,
        project_id=project_id,
        user_id=user_id,
        memory=SQLAlchemyMemoryStore(db),
    )


@router.post(
    "/projects/{project_id}/orchestrate",
    response_model=OrchestrateResponse,
)
def orchestrate(
    project_id: int,
    payload: OrchestrateRequest,
    db: Session = Depends(get_db),
) -> OrchestrateResponse:
    """Run the Orchestrator agent on a free-form instruction.

    Phase H8: wires the Memory store + (optionally) auto-save extractor.
    """
    import app.ai.tools  # noqa: F401

    auto_save = _resolve_auto_save(payload.auto_save_memory)
    ctx = _build_ctx_with_memory(db, project_id, payload.user_id)
    agent = _build_production_orchestrator(auto_save)
    history = [{"role": t.role, "content": t.content} for t in payload.conversation_history]
    result = agent.run(ctx, payload.instruction, conversation_history=history)

    saved = (result.extra or {}).get("auto_saved_memories", []) if result.extra else []

    return OrchestrateResponse(
        answer=result.answer,
        tool_calls_made=result.tool_call_count,
        error=result.error,
        auto_saved_memories=list(saved),
    )


@router.post(
    "/projects/{project_id}/orchestrate/stream",
)
def orchestrate_stream(
    project_id: int,
    payload: OrchestrateRequest,
    db: Session = Depends(get_db),
):
    """Run the Orchestrator agent with SSE streaming."""
    import app.ai.tools  # noqa: F401

    from app.ai.framework.types import AgentResult, AgentStep

    step_queue: queue.Queue[AgentStep | None] = queue.Queue()
    result_holder: list[AgentResult] = []

    def on_step(step: AgentStep):
        step_queue.put(step)

    auto_save = _resolve_auto_save(payload.auto_save_memory)
    user_id = payload.user_id
    history = [{"role": t.role, "content": t.content} for t in payload.conversation_history]

    def run_agent():
        from app.db.session import SessionLocal
        thread_db = SessionLocal()
        try:
            ctx = _build_ctx_with_memory(thread_db, project_id, user_id)
            agent = _build_production_orchestrator(auto_save)
            result = agent.stream_run(
                ctx,
                payload.instruction,
                on_step=on_step,
                conversation_history=history,
            )
            result_holder.append(result)
        except Exception as exc:
            logger.error("Orchestrator failed: %s", exc)
            result_holder.append(AgentResult(answer=f"调度失败: {exc}", error="orchestrator_error"))
        finally:
            thread_db.close()
            step_queue.put(None)

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    def event_stream() -> Generator[str, None, None]:
        # Heartbeat every 15s to defeat proxy/browser idle timeouts even when
        # the LLM is mid-generation with no new step events.
        HEARTBEAT_S = 15.0
        while True:
            try:
                step = step_queue.get(timeout=HEARTBEAT_S)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if step is None:
                if result_holder:
                    r = result_holder[0]
                    saved = (r.extra or {}).get("auto_saved_memories", []) if r.extra else []
                    final = {
                        "type": "done",
                        "answer": r.answer,
                        "error": r.error,
                        "auto_saved_memories": list(saved),
                    }
                    yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                break
            data = {
                "type": step.type.value if hasattr(step.type, 'value') else step.type,
                "content": step.content,
                "tool_name": step.tool_name,
                "tool_args": step.tool_args,
                "tool_result": step.tool_result[:500] if step.tool_result else "",
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── Pricing Pipeline endpoint ────────────────────────────────────

@router.post(
    "/projects/{project_id}/boq-items/{boq_item_id}/pipeline/pricing",
    response_model=PipelineResponse,
)
def run_pricing_pipeline(
    project_id: int,
    boq_item_id: int,
    db: Session = Depends(get_db),
) -> PipelineResponse:
    """Run the full pricing pipeline for a BOQ item."""
    import app.ai.tools  # noqa: F401

    from app.ai.framework.context import AgentContext
    from app.ai.pipelines.pricing_pipeline import build_pricing_pipeline

    ctx = AgentContext(db=db, project_id=project_id, boq_item_id=boq_item_id)
    pipeline = build_pricing_pipeline()
    result = pipeline.run(ctx)

    return PipelineResponse(
        pipeline=result.pipeline_name,
        stages=[
            PipelineStageOut(
                index=s.stage_index,
                agent=s.agent_name,
                success=s.success,
                duration_s=round(s.duration_s, 1),
                tool_calls=s.result.tool_call_count,
                answer=s.answer[:500],
            )
            for s in result.stages
        ],
        final_answer=result.final_answer,
        success=result.success,
        total_duration_s=round(result.total_duration_s, 1),
        error=result.error,
    )


# ── Audit Pipeline endpoint ──────────────────────────────────────

@router.post(
    "/projects/{project_id}/pipeline/audit",
    response_model=PipelineResponse,
)
def run_audit_pipeline(
    project_id: int,
    db: Session = Depends(get_db),
) -> PipelineResponse:
    """Run the full audit pipeline for a project."""
    import app.ai.tools  # noqa: F401

    from app.ai.framework.context import AgentContext
    from app.ai.pipelines.audit_pipeline import build_audit_pipeline

    ctx = AgentContext(db=db, project_id=project_id)
    pipeline = build_audit_pipeline()
    result = pipeline.run(ctx)

    return PipelineResponse(
        pipeline=result.pipeline_name,
        stages=[
            PipelineStageOut(
                index=s.stage_index,
                agent=s.agent_name,
                success=s.success,
                duration_s=round(s.duration_s, 1),
                tool_calls=s.result.tool_call_count,
                answer=s.answer[:500],
            )
            for s in result.stages
        ],
        final_answer=result.final_answer,
        success=result.success,
        total_duration_s=round(result.total_duration_s, 1),
        error=result.error,
    )

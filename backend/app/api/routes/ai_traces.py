"""AI Traces & Cost Dashboard API endpoints.

Provides:
- GET /ai/traces — list recent agent traces with filtering
- GET /ai/traces/stats — aggregated token usage and cost statistics
- GET /ai/traces/{id} — single trace detail
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.agent_trace import AgentTrace

router = APIRouter(tags=["ai-traces"])


# ── Schemas ──────────────────────────────────────────────────────

class TraceOut(BaseModel):
    id: int
    project_id: int | None
    agent_name: str
    parent_trace_id: int | None
    model: str | None
    provider: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_cents: float
    turns_used: int
    tool_calls_made: int
    duration_ms: int
    success: bool
    error: str | None
    answer_preview: str | None
    started_at: str
    finished_at: str | None


class TraceDetailOut(TraceOut):
    instruction: str | None
    steps_json: str | None


class TraceListResponse(BaseModel):
    total: int
    traces: list[TraceOut]


class CostStatsResponse(BaseModel):
    period: str
    total_traces: int
    successful_traces: int
    failed_traces: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_cents: float
    total_tool_calls: int
    avg_duration_ms: float
    by_agent: list[AgentStats]
    by_day: list[DayStats]


class AgentStats(BaseModel):
    agent_name: str
    trace_count: int
    total_tokens: int
    total_cost_cents: float
    avg_duration_ms: float
    success_rate: float


class DayStats(BaseModel):
    date: str
    trace_count: int
    total_tokens: int
    total_cost_cents: float


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/ai/traces", response_model=TraceListResponse)
def list_traces(
    project_id: int | None = Query(None),
    agent_name: str | None = Query(None),
    success: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> TraceListResponse:
    """List recent agent traces with optional filters."""
    q = db.query(AgentTrace)

    if project_id is not None:
        q = q.filter(AgentTrace.project_id == project_id)
    if agent_name is not None:
        q = q.filter(AgentTrace.agent_name == agent_name)
    if success is not None:
        q = q.filter(AgentTrace.success == (1 if success else 0))

    total = q.count()
    rows = q.order_by(AgentTrace.id.desc()).offset(offset).limit(limit).all()

    return TraceListResponse(
        total=total,
        traces=[_to_trace_out(r) for r in rows],
    )


@router.get("/ai/traces/stats", response_model=CostStatsResponse)
def trace_stats(
    project_id: int | None = Query(None),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> CostStatsResponse:
    """Aggregated cost and usage statistics."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q = db.query(AgentTrace).filter(AgentTrace.started_at >= cutoff)
    if project_id is not None:
        q = q.filter(AgentTrace.project_id == project_id)

    rows = q.all()

    total_traces = len(rows)
    successful = sum(1 for r in rows if r.success == 1)
    failed = total_traces - successful
    total_input = sum(r.input_tokens for r in rows)
    total_output = sum(r.output_tokens for r in rows)
    total_tok = sum(r.total_tokens for r in rows)
    total_cost = sum(r.estimated_cost_cents for r in rows)
    total_tools = sum(r.tool_calls_made for r in rows)
    avg_dur = sum(r.duration_ms for r in rows) / max(total_traces, 1)

    # By agent
    agent_map: dict[str, list[AgentTrace]] = {}
    for r in rows:
        agent_map.setdefault(r.agent_name, []).append(r)

    by_agent = [
        AgentStats(
            agent_name=name,
            trace_count=len(traces),
            total_tokens=sum(t.total_tokens for t in traces),
            total_cost_cents=round(sum(t.estimated_cost_cents for t in traces), 2),
            avg_duration_ms=round(sum(t.duration_ms for t in traces) / max(len(traces), 1)),
            success_rate=round(sum(1 for t in traces if t.success == 1) / max(len(traces), 1), 3),
        )
        for name, traces in sorted(agent_map.items())
    ]

    # By day
    day_map: dict[str, list[AgentTrace]] = {}
    for r in rows:
        day = r.started_at[:10] if r.started_at else "unknown"
        day_map.setdefault(day, []).append(r)

    by_day = [
        DayStats(
            date=day,
            trace_count=len(traces),
            total_tokens=sum(t.total_tokens for t in traces),
            total_cost_cents=round(sum(t.estimated_cost_cents for t in traces), 2),
        )
        for day, traces in sorted(day_map.items())
    ]

    return CostStatsResponse(
        period=f"last_{days}_days",
        total_traces=total_traces,
        successful_traces=successful,
        failed_traces=failed,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_tok,
        total_cost_cents=round(total_cost, 2),
        total_tool_calls=total_tools,
        avg_duration_ms=round(avg_dur),
        by_agent=by_agent,
        by_day=by_day,
    )


@router.get("/ai/traces/{trace_id}", response_model=TraceDetailOut)
def get_trace_detail(
    trace_id: int,
    db: Session = Depends(get_db),
) -> TraceDetailOut:
    """Get detailed info for a single trace."""
    row = db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trace not found")

    return TraceDetailOut(
        id=row.id,
        project_id=row.project_id,
        agent_name=row.agent_name,
        parent_trace_id=row.parent_trace_id,
        model=row.model,
        provider=row.provider,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        estimated_cost_cents=row.estimated_cost_cents,
        turns_used=row.turns_used,
        tool_calls_made=row.tool_calls_made,
        duration_ms=row.duration_ms,
        success=row.success == 1,
        error=row.error,
        answer_preview=row.answer_preview,
        started_at=row.started_at,
        finished_at=row.finished_at,
        instruction=row.instruction,
        steps_json=row.steps_json,
    )


def _to_trace_out(row: AgentTrace) -> TraceOut:
    return TraceOut(
        id=row.id,
        project_id=row.project_id,
        agent_name=row.agent_name,
        parent_trace_id=row.parent_trace_id,
        model=row.model,
        provider=row.provider,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        estimated_cost_cents=row.estimated_cost_cents,
        turns_used=row.turns_used,
        tool_calls_made=row.tool_calls_made,
        duration_ms=row.duration_ms,
        success=row.success == 1,
        error=row.error,
        answer_preview=row.answer_preview,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )

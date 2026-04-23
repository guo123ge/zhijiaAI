"""AgentTrace — persists every agent run for observability and cost tracking.

Each row = one agent.run() invocation, storing:
- who/what/when
- token usage (input + output)
- tool calls made
- duration
- success/error status
- estimated cost
"""

from datetime import datetime, timezone

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Context
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    parent_trace_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Task
    instruction: Mapped[str] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=True)

    # Token usage
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Cost (USD cents)
    estimated_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Execution
    turns_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls_made: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Result
    success: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1=success, 0=failure
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answer_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Steps JSON (compact)
    steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    started_at: Mapped[str] = mapped_column(
        String(50), nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    finished_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

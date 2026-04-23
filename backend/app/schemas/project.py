from datetime import date, datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    region: str
    description: str | None = None
    project_type: str = "住宅"  # 住宅|商业|工业|公共建筑|市政
    budget: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    owner: str | None = None
    standard_type: str = "GB50500"  # GB50500 | HKSMM4
    language: str = "zh"  # zh | en | bilingual
    currency: str = "CNY"  # CNY | HKD


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    region: str | None = None
    project_type: str | None = None
    budget: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    owner: str | None = None
    standard_type: str | None = None
    language: str | None = None
    currency: str | None = None


class ProjectStatusUpdate(BaseModel):
    status: str  # draft|ongoing|completed|archived


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    region: str
    project_type: str = "住宅"
    status: str = "draft"
    budget: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    owner: str | None = None
    standard_type: str = "GB50500"
    language: str = "zh"
    currency: str = "CNY"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class DivisionStat(BaseModel):
    division: str
    count: int
    cost: float


class DashboardSummaryOut(BaseModel):
    project_id: int
    boq_count: int
    unbound_count: int
    dirty_count: int
    validation_total: int
    validation_errors: int
    validation_warnings: int
    recent_audit_count: int
    recent_comment_count: int
    # New fields
    calc_total: float = 0
    binding_rate: str = "0%"
    budget: float | None = None
    top_divisions: list[DivisionStat] = []


class HealthScoreDimension(BaseModel):
    name: str
    score: int  # 0-100
    weight: float
    detail: str


class HealthScoreOut(BaseModel):
    project_id: int
    overall_score: int  # 0-100
    grade: str  # A/B/C/D/F
    dimensions: list[HealthScoreDimension]
    suggestions: list[str]

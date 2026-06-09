import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

from app.api.routes.agent_validate import router as agent_validate_router
from app.api.routes.agent_valuate import router as agent_valuate_router
from app.api.routes.ai_analyze import router as ai_analyze_router
from app.api.routes.auto_valuate import router as auto_valuate_router
from app.api.routes.ai_chat import router as ai_chat_router
from app.api.routes.ai_settings import router as ai_settings_router
from app.api.routes.ai_enhanced import router as ai_enhanced_router
from app.api.routes.auth import router as auth_router
from app.api.routes.graph import router as graph_router
from app.api.routes.orchestrator import router as orchestrator_router
from app.api.routes.ai_traces import router as ai_traces_router
from app.api.routes.memories import router as memories_router
from app.api.routes.quota_items import router as quota_items_router
from app.api.routes.skills import router as skills_router
from app.api.routes.knowledge_links import router as knowledge_links_router
from app.api.routes.knowledge_notes import router as knowledge_notes_router
from app.api.routes.tags import router as tags_router
from app.api.routes.audit_logs import router as audit_logs_router
from app.api.routes.bindings import router as bindings_router
from app.api.routes.boq_generate import router as boq_generate_router
from app.api.routes.drawing_recognition import router as drawing_recognition_router
from app.api.routes.boq_items import router as boq_items_router
from app.api.routes.calculate import router as calculate_router
from app.api.routes.collaboration import router as collaboration_router
from app.api.routes.exports import router as exports_router
from app.api.routes.reports import router as reports_router
from app.api.routes.health import router as health_router
from app.api.routes.imports import router as imports_router
from app.api.routes.match import router as match_router
from app.api.routes.material_prices import router as material_prices_router
from app.api.routes.measures import router as measures_router
from app.api.routes.projects import router as projects_router
from app.api.routes.provenance import router as provenance_router
from app.api.routes.query import router as query_router
from app.api.routes.rule_packages import router as rule_packages_router
from app.api.routes.snapshots import router as snapshots_router
from app.api.routes.standard_codes import router as standard_codes_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.validation import router as validation_router
from app.api.routes.valuation_management import router as valuation_management_router
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.user import User
from app.services.activation_service import get_active_trial
from app.services.auth_service import decode_access_token

AuthSessionLocal = SessionLocal
ENFORCE_ACTIVATION = os.getenv("ENFORCE_ACTIVATION", "1") != "0"

# Import models so SQLAlchemy is aware of them for metadata.create_all
import app.models  # noqa: F401

app = FastAPI(title="AI Native Valuation Backend", version="0.1.0")

def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if not raw:
        return ["*"] if os.getenv("APP_ENV", "development").lower() != "production" else []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/trial/activate",
}


@app.middleware("http")
async def enforce_api_activation(request: Request, call_next):
    if not ENFORCE_ACTIVATION:
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "请先输入激活码"})
    payload = decode_access_token(authorization[7:])
    if not payload:
        return JSONResponse(status_code=401, content={"detail": "激活状态已失效，请重新激活"})

    db = AuthSessionLocal()
    try:
        user_id = int(payload.get("sub", 0))
        user = db.query(User).filter(User.id == user_id, User.is_active == 1).first()
        if not user:
            return JSONResponse(status_code=401, content={"detail": "用户不存在或已停用"})
        if user.role != "owner" and not get_active_trial(db, user.id):
            return JSONResponse(status_code=401, content={"detail": "试用已过期或未激活"})
    finally:
        db.close()
    return await call_next(request)


@app.on_event("startup")
def _create_tables() -> None:
    # MVP/dev convenience. Replace with migrations (Alembic) later.
    Base.metadata.create_all(bind=engine)
    _migrate_dev_schema()
    _load_ai_settings_from_db()


def _load_ai_settings_from_db() -> None:
    """Restore persisted AI settings into os.environ so get_ai_settings() picks them up."""
    import os
    from app.db.session import SessionLocal
    from app.models.system_setting import SystemSetting

    db = SessionLocal()
    try:
        rows = db.query(SystemSetting).filter(SystemSetting.key.like("AI_%")).all()
        for row in rows:
            if row.value:  # only set non-empty values
                os.environ[row.key] = row.value
    except Exception:
        pass  # DB may not exist yet on first run
    finally:
        db.close()


def _migrate_dev_schema() -> None:
    """Best-effort dev migration for local DB files without Alembic."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    # --- projects: add standard_type / language / currency ---
    if "projects" in tables:
        proj_cols = {c["name"] for c in inspector.get_columns("projects")}
        with engine.begin() as conn:
            if "standard_type" not in proj_cols:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN standard_type VARCHAR(50) NOT NULL DEFAULT 'GB50500'"
                ))
            if "language" not in proj_cols:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN language VARCHAR(20) NOT NULL DEFAULT 'zh'"
                ))
            if "currency" not in proj_cols:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN currency VARCHAR(10) NOT NULL DEFAULT 'CNY'"
                ))

    # --- line_item_quota_bindings: add coefficient ---
    if "line_item_quota_bindings" not in tables:
        return
    columns = {c["name"] for c in inspector.get_columns("line_item_quota_bindings")}
    if "coefficient" in columns:
        return

    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect == "sqlite":
            conn.execute(
                text(
                    "ALTER TABLE line_item_quota_bindings "
                    "ADD COLUMN coefficient FLOAT NOT NULL DEFAULT 1.0"
                )
            )
        else:
            conn.execute(
                text(
                    "ALTER TABLE line_item_quota_bindings "
                    "ADD COLUMN coefficient DOUBLE PRECISION NOT NULL DEFAULT 1.0"
                )
            )


app.include_router(health_router)
app.include_router(projects_router, prefix="/api")
app.include_router(boq_items_router, prefix="/api")
app.include_router(boq_generate_router, prefix="/api")
app.include_router(bindings_router, prefix="/api")
app.include_router(match_router, prefix="/api")
app.include_router(calculate_router, prefix="/api")
app.include_router(imports_router, prefix="/api")
app.include_router(exports_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(provenance_router, prefix="/api")
app.include_router(rule_packages_router, prefix="/api")
app.include_router(material_prices_router, prefix="/api")
app.include_router(snapshots_router, prefix="/api")
app.include_router(measures_router, prefix="/api")
app.include_router(collaboration_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(audit_logs_router, prefix="/api")
app.include_router(validation_router, prefix="/api")
app.include_router(valuation_management_router, prefix="/api")
app.include_router(standard_codes_router, prefix="/api")
app.include_router(ai_settings_router, prefix="/api")
app.include_router(ai_analyze_router, prefix="/api")
app.include_router(auto_valuate_router, prefix="/api")
app.include_router(ai_chat_router, prefix="/api")
app.include_router(agent_valuate_router, prefix="/api")
app.include_router(agent_validate_router, prefix="/api")
app.include_router(drawing_recognition_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(ai_enhanced_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(tags_router, prefix="/api")
app.include_router(knowledge_links_router, prefix="/api")
app.include_router(knowledge_notes_router, prefix="/api")
app.include_router(graph_router, prefix="/api")
app.include_router(orchestrator_router, prefix="/api")
app.include_router(ai_traces_router, prefix="/api")
app.include_router(memories_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
app.include_router(quota_items_router, prefix="/api")

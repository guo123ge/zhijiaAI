"""Shared test fixtures: in-memory SQLite DB + FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 – register all ORM models
from app.db.base import Base
from app.db.session import get_db
import app.main as main_module
from app.main import app
from app.models.user import User
from app.services.auth_service import create_access_token

engine = create_engine(
    "sqlite:///file:testdb?mode=memory&cache=shared&uri=true",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
main_module.AuthSessionLocal = TestSession
main_module.ENFORCE_ACTIVATION = False


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        session = TestSession()
        try:
            user = User(
                username="test_owner",
                hashed_password="test-only",
                display_name="Test Owner",
                role="owner",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            c.headers.update({"Authorization": f"Bearer {create_access_token(user.id, user.username, user.role)}"})
        finally:
            session.close()
        yield c


@pytest.fixture()
def db():
    """Yield a raw DB session for seeding test data."""
    session = TestSession()
    yield session
    session.close()

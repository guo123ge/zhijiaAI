#!/usr/bin/env python
"""Initialize database tables and seed baseline data."""

import importlib.util
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402


def _run_seed_script(filename: str) -> None:
    script_path = BACKEND_ROOT / filename
    spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load seed script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def init_database() -> None:
    print("[1/3] Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("[1/3] Database tables are ready.")


def load_standard_codes() -> None:
    print("[2/3] Loading standard BOQ codes...")
    _run_seed_script("seed_standard_codes.py")
    print("[2/3] Standard BOQ codes loaded.")


def load_quota_items() -> None:
    print("[3/3] Loading quota items...")
    _run_seed_script("seed_quota.py")
    print("[3/3] Quota items loaded.")


def main() -> None:
    print("=" * 50)
    print("AI Cost database initialization")
    print("=" * 50)
    init_database()
    load_standard_codes()
    load_quota_items()
    print("=" * 50)
    print("Done. Frontend: http://localhost:5173/aicost/")
    print("Docs: http://localhost:8000/docs")


if __name__ == "__main__":
    os.chdir(BACKEND_ROOT)
    main()

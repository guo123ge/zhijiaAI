#!/usr/bin/env python
"""Start the FastAPI backend with the expected local port."""

import os
import sys
from pathlib import Path

import uvicorn

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))


def main() -> None:
    os.chdir(BACKEND_ROOT)
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting AI Cost API at http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

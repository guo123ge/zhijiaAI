"""Generate one-time trial activation codes.

Example:
    python scripts/generate_activation_codes.py --days 7 --count 5 --note "June beta"
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.services.activation_service import create_activation_code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, choices=(7, 14), required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        for _ in range(args.count):
            print(create_activation_code(db, days=args.days, note=args.note))
    finally:
        db.close()


if __name__ == "__main__":
    main()

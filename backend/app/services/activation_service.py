"""Activation code and trial access helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.activation_code import ActivationCode
from app.models.trial_activation import TrialActivation
from app.models.user import User


def normalize_code(code: str) -> str:
    return "".join(code.strip().upper().split())


def hash_activation_code(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def generate_plain_code(days: int) -> str:
    prefix = f"AICOST-{days}D"
    part1 = secrets.token_hex(2).upper()
    part2 = secrets.token_hex(2).upper()
    part3 = secrets.token_hex(2).upper()
    return f"{prefix}-{part1}-{part2}-{part3}"


def create_activation_code(
    db: Session,
    *,
    days: int,
    note: str = "",
    expires_at: datetime | None = None,
) -> str:
    code = generate_plain_code(days)
    row = ActivationCode(
        code_hash=hash_activation_code(code),
        trial_days=days,
        note=note,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    return code


def get_active_trial(db: Session, user_id: int) -> TrialActivation | None:
    now = datetime.now(timezone.utc)
    return (
        db.query(TrialActivation)
        .filter(TrialActivation.user_id == user_id, TrialActivation.ends_at > now)
        .order_by(TrialActivation.ends_at.desc())
        .first()
    )


def create_trial_user(db: Session, code: str) -> User:
    suffix = hashlib.sha1(normalize_code(code).encode("utf-8")).hexdigest()[:12]
    username = f"trial_{suffix}"
    user = db.query(User).filter(User.username == username).first()
    if user:
        return user
    user = User(
        username=username,
        hashed_password=f"activation:{secrets.token_urlsafe(24)}",
        display_name="试用用户",
        role="viewer",
    )
    db.add(user)
    db.flush()
    return user


def activate_trial_code(db: Session, *, code: str, requested_days: int) -> tuple[User, TrialActivation]:
    code_hash = hash_activation_code(code)
    row = db.query(ActivationCode).filter(ActivationCode.code_hash == code_hash).first()
    now = datetime.now(timezone.utc)
    if not row:
        raise ValueError("激活码不存在")
    if row.is_used:
        raise ValueError("激活码已使用")
    expires_at = _as_aware(row.expires_at)
    if expires_at and expires_at <= now:
        raise ValueError("激活码已过期")
    if row.trial_days != requested_days:
        raise ValueError(f"该激活码仅适用于 {row.trial_days} 天试用")

    user = create_trial_user(db, code)
    started_at = now
    ends_at = started_at + timedelta(days=row.trial_days)
    trial = TrialActivation(
        user_id=user.id,
        activation_code_id=row.id,
        trial_days=row.trial_days,
        started_at=started_at,
        ends_at=ends_at,
    )
    db.add(trial)
    row.is_used = 1
    row.used_by_user_id = user.id
    row.used_at = now
    db.commit()
    db.refresh(user)
    db.refresh(trial)
    return user, trial


def trial_payload(trial: TrialActivation) -> dict:
    now = datetime.now(timezone.utc)
    ends_at = _as_aware(trial.ends_at) or now
    started_at = _as_aware(trial.started_at) or now
    delta = ends_at - now
    remaining_days = max(0, delta.days + (1 if delta.seconds else 0))
    return {
        "active": ends_at > now,
        "trial_days": trial.trial_days,
        "remaining_days": remaining_days,
        "started_at": started_at.isoformat(),
        "ends_at": ends_at.isoformat(),
    }


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

"""Authentication: sessions, passwords, guards."""
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException, Depends, Response
from sqlalchemy.orm import Session
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from database import User, Session as DBSession, get_db

ph = PasswordHasher()
SESSION_COOKIE = "sid"
SESSION_DAYS = 30


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def hash_password(pw: str) -> str:
    return ph.hash(pw)


def verify_password(pw: str, pw_hash: str) -> bool:
    try:
        return ph.verify(pw_hash, pw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def set_session_cookie(response: Response, sid: str, remember: bool = True):
    max_age = SESSION_DAYS * 86400 if remember else None
    response.set_cookie(
        SESSION_COOKIE, sid,
        max_age=max_age,
        httponly=True,
        secure=os.environ.get("ATOM_COOKIE_SECURE", "1") == "1",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")


def create_session(db: Session, user_id: str, user_agent: str = "", ip: str = "") -> DBSession:
    # revoke all existing sessions for this user? No — keep other devices, just create new
    sid = new_session_id()
    now = _utcnow()
    s = DBSession(
        id=sid, user_id=user_id,
        expires_at=now + timedelta(days=SESSION_DAYS),
        created_at=now, last_seen_at=now,
        user_agent=user_agent[:255] if user_agent else None,
        ip_hash=hashlib.sha256(ip.encode()).hexdigest()[:16] if ip else None,
    )
    db.add(s)
    db.commit()
    return s


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def get_session_user(db: Session, sid: str):
    if not sid:
        return None
    s = db.query(DBSession).filter(DBSession.id == sid).first()
    if not s or s.revoked_at is not None:
        return None
    now = _utcnow()
    expires = _naive(s.expires_at)
    if expires < now:
        return None
    # sliding renewal
    if (expires - now) < timedelta(days=15):
        s.expires_at = now + timedelta(days=SESSION_DAYS)
    s.last_seen_at = now
    db.commit()
    return s


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    sid = request.cookies.get(SESSION_COOKIE)
    s = get_session_user(db, sid)
    if not s:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == s.user_id).first()
    if not user or user.status != "ACTIVE":
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    return get_current_user(request, db)

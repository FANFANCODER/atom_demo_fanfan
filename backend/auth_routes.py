"""Auth routes: register, login, logout, me, change-password."""
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
import secrets

from database import User, get_db
from auth import (
    hash_password, verify_password, create_session, set_session_cookie,
    clear_session_cookie, get_current_user, SESSION_DAYS,
)
from database import Session as DBSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Simple in-memory rate limit counters (email+ip)
LOGIN_FAILS: dict[str, list[datetime]] = {}
REG_FAILS: dict[str, list[datetime]] = {}


def _rate_limit(bucket: dict, key: str, max_count: int, window_sec: int) -> bool:
    from datetime import timedelta
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(seconds=window_sec)
    bucket[key] = [t for t in bucket.get(key, []) if t > cutoff]
    if len(bucket[key]) >= max_count:
        return False
    return True


def _record_fail(bucket: dict, key: str):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    bucket.setdefault(key, []).append(now)


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str
    remember: bool = True


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


def valid_password(pw: str) -> bool:
    return len(pw) >= 8


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else ""
    if not _rate_limit(REG_FAILS, ip, 3, 3600):
        raise HTTPException(status_code=429, detail="Too many attempts")
    email = body.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Invalid email")
    if not valid_password(body.password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if db.query(User).filter(User.email == email).first():
        _record_fail(REG_FAILS, ip)
        raise HTTPException(status_code=400, detail="Invalid credentials")
    user = User(
        id=secrets.token_urlsafe(16),
        email=email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    s = create_session(db, user.id, request.headers.get("user-agent", ""), ip)
    set_session_cookie(response, s.id, remember=True)
    return {"ok": True, "user": {"id": user.id, "email": user.email}}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else ""
    key = f"{body.email.lower()}|{ip}"
    if not _rate_limit(LOGIN_FAILS, key, 5, 900):
        raise HTTPException(status_code=429, detail="Too many attempts")
    user = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        _record_fail(LOGIN_FAILS, key)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="Account disabled")
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    s = create_session(db, user.id, request.headers.get("user-agent", ""), ip)
    db.commit()
    set_session_cookie(response, s.id, remember=body.remember)
    return {"ok": True, "user": {"id": user.id, "email": user.email}}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    sid = request.cookies.get("sid")
    if sid:
        s = db.query(DBSession).filter(DBSession.id == sid).first()
        if s:
            s.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "plan": user.plan, "status": user.status}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid current password")
    if not valid_password(body.new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    # revoke all other sessions
    sid = request.cookies.get("sid")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(DBSession).filter(
        DBSession.user_id == user.id, DBSession.id != sid, DBSession.revoked_at.is_(None)
    ).update({DBSession.revoked_at: now}, synchronize_session=False)
    db.commit()
    return {"ok": True}

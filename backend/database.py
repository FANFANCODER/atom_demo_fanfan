"""SQLAlchemy database setup and models for Atom."""
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import (
    create_engine, Column, String, Boolean, Integer, DateTime, Text, ForeignKey, JSON, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# Database URL: Postgres on Vercel, SQLite locally.
# Vercel Postgres provides POSTGRES_URL; you can also set DATABASE_URL directly.
DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if not DB_URL:
    DB_PATH = os.environ.get("ATOM_DB_PATH", os.path.join(os.path.dirname(__file__), "atom.db"))
    DB_URL = f"sqlite:///{DB_PATH}"

# Vercel Postgres URLs may start with postgres:// or postgresql://.
# SQLAlchemy 2.x defaults to psycopg3; we use psycopg2-binary, so force +psycopg2.
if DB_URL.startswith("postgres://"):
    DB_URL = "postgresql+psycopg2://" + DB_URL[len("postgres://"):]
elif DB_URL.startswith("postgresql://"):
    DB_URL = "postgresql+psycopg2://" + DB_URL[len("postgresql://"):]

# Neon requires SSL; ensure sslmode=require is present.
if DB_URL.startswith("postgresql+psycopg2://") and "sslmode=" not in DB_URL:
    sep = "&" if "?" in DB_URL else "?"
    DB_URL = f"{DB_URL}{sep}sslmode=require"

_connect_args = {}
if DB_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(DB_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    email_verified = Column(Boolean, default=False)
    plan = Column(String, default="FREE")
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime, nullable=True)

    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user_agent = Column(String, nullable=True)
    ip_hash = Column(String, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")


class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    template_type = Column(String, default="static-html")
    status = Column(String, default="BUILDING")
    public_url = Column(String, nullable=True)
    sandbox_id = Column(String, nullable=True)
    sandbox_state = Column(String, default="COLD")
    last_active_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="projects")
    messages = relationship("Message", back_populates="project", cascade="all, delete-orphan")
    snapshots = relationship("FileSnapshot", back_populates="project", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_projects_user_updated", "user_id", "updated_at"),)


class FileSnapshot(Base):
    __tablename__ = "file_snapshots"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(String, nullable=True)
    tree = Column(JSON, default=dict)
    storage_key = Column(String, nullable=False)
    size_bytes = Column(Integer, default=0)
    is_latest = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="snapshots")

    __table_args__ = (Index("idx_snap_proj_latest", "project_id", "is_latest"),)


class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, default="")
    tool_calls = Column(JSON, nullable=True)
    tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="messages")


class Deployment(Base):
    __tablename__ = "deployments"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, default="QUEUED")
    kind = Column(String, default="static")
    artifact_key = Column(String, nullable=True)
    url = Column(String, nullable=True)
    build_log_key = Column(String, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="deployments")


def init_db():
    Base.metadata.create_all(bind=engine)

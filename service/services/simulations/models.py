from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from service.models.db.base_db_model import Base


class SimulationRun(Base):
    __tablename__ = "simulation_run"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_simulation_request"),
        {"schema": "profile"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.user.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.user_launch.id"), unique=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profile.simulation_run.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    configuration: Mapped[dict] = mapped_column(JSONB)
    configuration_sha256: Mapped[str] = mapped_column(String(64))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SimulationAttempt(Base):
    __tablename__ = "simulation_attempt"
    __table_args__ = {"schema": "profile"}
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.simulation_run.id"), index=True)
    state: Mapped[str] = mapped_column(String(24))
    number: Mapped[int] = mapped_column(Integer)
    executor: Mapped[str] = mapped_column(String(100))


class SimulationArtifact(Base):
    __tablename__ = "simulation_artifact"
    __table_args__ = (
        UniqueConstraint("run_id", "name", name="uq_simulation_artifact"),
        {"schema": "profile"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.simulation_run.id"), index=True)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.user_file.id"))
    name: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from service.models.db.base_db_model import Base
from service.models.key_value import (
    ProcessingStatus,
    ServiceType,
    SessionStatus,
)


class User(Base):
    __tablename__ = "user"
    __table_args__ = {"schema": "profile"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4, comment="Unique user identifier"
    )
    email: Mapped[str] = mapped_column(String(500), unique=True, comment="User email address")
    password_hash: Mapped[str] = mapped_column(String(255), comment="Hashed user password")
    available_launches: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Number of available launches"
    )
    first_name: Mapped[str | None] = mapped_column(String(50), comment="User first name")
    timezone: Mapped[str | None] = mapped_column(String(50), comment="Preferred timezone name")
    avatar_url: Mapped[str | None] = mapped_column(String(1000), comment="Public avatar URL")
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
        comment="Admin role flag (in addition to env SERVICE__ADMIN_USER_IDS)",
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
        comment="Whether the user confirmed their email via code",
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the email was confirmed"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
        comment="Whether the account is active; false = blocked by admin",
    )
    # Раздельные согласия при регистрации (152-ФЗ, с 01.09.2025). NULL = грандфатеринг.
    consent_pd_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When general PD-processing consent was given",
    )
    consent_transfer_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When separate LLM-transfer/cross-border consent was given",
    )
    marketing_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Separate, voluntary consent to marketing email (ФЗ «О рекламе», ст. 18)",
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Global opt-out: suppresses ALL mail, including service notices",
    )
    consent_version: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Version of legal documents accepted at registration"
    )

    user_launches: Mapped[list[UserLaunch]] = relationship(
        cascade="all, delete-orphan",
        back_populates="user",
        lazy="selectin",
    )

    # Files owned by the user
    user_files: Mapped[list[UserFile]] = relationship(
        cascade="all, delete-orphan",
        back_populates="user",
        lazy="selectin",
    )


class UserLaunch(Base):
    __tablename__ = "user_launch"
    __table_args__ = {"schema": "profile"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4, comment="Unique launch identifier"
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile.user.id", ondelete="CASCADE"),
        index=True,
        comment="Reference to user",
    )
    type: Mapped[ServiceType] = mapped_column(
        Enum(ServiceType, name="service_type", create_type=True), comment="Launch type"
    )
    status: Mapped[ProcessingStatus] = mapped_column(String(50), comment="Launch status")
    payload: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Optional JSON payload with job parameters"
    )

    # Celery task tracking
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Celery task ID for job tracking"
    )
    celery_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Celery task status"
    )

    user: Mapped[User] = relationship(
        back_populates="user_launches",
        lazy="selectin",
    )


class UserSession(Base):
    __tablename__ = "user_session"
    __table_args__ = {"schema": "session"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4, comment="Unique session identifier"
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True, comment="Reference to user")
    fingerprint: Mapped[str | None] = mapped_column(String(50), comment="Browser fingerprint hash")
    user_agent: Mapped[str | None] = mapped_column(String(255), comment="Browser user agent string")
    status: Mapped[SessionStatus] = mapped_column(String, comment="Session status")
    token: Mapped[str | None] = mapped_column(String, comment="Session authentication token")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="Session expiration timestamp"
    )
    session_code: Mapped[str] = mapped_column(String, comment="Session verification code")


class UserFile(Base):
    __tablename__ = "user_file"
    __table_args__ = (
        UniqueConstraint("user_id", "upload_intent_id", name="uq_user_file_user_upload_intent"),
        {"schema": "profile"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4, comment="Unique image identifier"
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile.user.id", ondelete="CASCADE"),
        index=True,
        comment="Reference to user",
    )
    type: Mapped[ServiceType] = mapped_column(
        # ``profile.user_file.mode`` was introduced as VARCHAR in the initial
        # schema and intentionally remains so: unlike ``user_launch.type`` it
        # has no enum migration.  Mapping it as PostgreSQL ``service_type``
        # made reads bind an enum parameter against a varchar column
        # (``varchar = service_type``) and turned the Work Library into a 500.
        # ``ServiceType`` is a ``StrEnum``, therefore callers retain the same
        # bounded value contract while SQL uses the actual column type.
        String(50),
        name="mode",
        comment="service type",
    )
    file_name: Mapped[str] = mapped_column(String(1000), comment="storage key")
    # 🔴 ИМЯ, ПОД КОТОРЫМ ФАЙЛ ПРИСЛАЛ ЧЕЛОВЕК. `file_name` выше — это КЛЮЧ ХРАНИЛИЩА
    # (`uploads/CHAT/123f5c3b….json`), и пока файлы жили только в объектном хранилище,
    # разница была незаметна. С приходом рабочего каталога они стали видимы: и в дереве
    # песочницы, и у агента в `ws_list` появлялись шестнадцатеричные имена, по которым не
    # понять, что это за файл. NULL у старых записей — исходного имени просто нет.
    original_name: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="name given by the uploader"
    )
    upload_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, nullable=True, comment="opaque client upload idempotency key"
    )
    content_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="internal upload identity hash"
    )
    file_url: Mapped[str] = mapped_column(String(1000), comment="file path or URL")

    user: Mapped[User] = relationship(
        back_populates="user_files",
        lazy="selectin",
    )


class DocumentPublicationJob(Base):
    """Durable delivery intent for one audited Document Forge artifact."""

    __tablename__ = "document_publication_job"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "build_id",
            "artifact_id",
            "role",
            name="uq_document_publication_identity",
        ),
        {"schema": "profile"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile.user.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), index=True)
    build_id: Mapped[str] = mapped_column(String(128))
    artifact_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    source_digest: Mapped[str] = mapped_column(String(64))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_size: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(1000))
    mime_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending_audit")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    billing_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profile.user_file.id", ondelete="SET NULL"), nullable=True
    )


class DocumentAuditAttempt(Base):
    """One accepted or potentially accepted visual-model audit invocation."""

    __tablename__ = "document_audit_attempt"
    __table_args__ = (
        Index(
            "uq_document_audit_attempt_open",
            "publication_job_id",
            unique=True,
            postgresql_where=text("state IN ('started','charge_pending')"),
        ),
        {"schema": "profile"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    publication_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile.document_publication_job.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile.user.id", ondelete="CASCADE"), index=True
    )
    build_id: Mapped[str] = mapped_column(String(128))
    source_digest: Mapped[str] = mapped_column(String(64))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), index=True, default="started")
    usage_envelope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reservation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

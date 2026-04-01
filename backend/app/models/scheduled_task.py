"""Scheduled Task model."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from app.database import Base
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.business import Business


class ScheduledTask(Base):
    """Scheduled Task model - represents a cron-based scheduled test execution."""

    __tablename__ = 'scheduled_tasks'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('businesses.id', ondelete='CASCADE'),
        nullable=False
    )

    # Task configuration
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Single environment + test cases (simplified version)
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('environments.id', ondelete='CASCADE'),
        nullable=False
    )
    test_case_ids: Mapped[List[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list
    )

    # Execution configuration
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    workers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    resolutions: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)

    # Cron configuration
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)

    # Notification
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    feishu_notify_user_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Execution tracking
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        onupdate=now_with_tz,
        nullable=False
    )

    # Relationships
    business: Mapped['Business'] = relationship(
        'Business',
        back_populates='scheduled_tasks'
    )

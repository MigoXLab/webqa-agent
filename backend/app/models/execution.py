"""Execution model."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.database import Base
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.environment import Environment


class Execution(Base):
    """Execution model - represents a test execution record."""

    __tablename__ = 'executions'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    business_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('businesses.id', ondelete='CASCADE'),
        nullable=True
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('environments.id', ondelete='SET NULL'),
        nullable=True
    )

    # Trigger type: manual / scheduled
    trigger_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default='manual'
    )

    # Associated scheduled task ID (optional)
    scheduled_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True
    )

    # Execution configuration
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    workers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    resolutions: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)

    # Test case IDs that were executed
    test_case_ids: Mapped[List[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list
    )

    # Status: pending / running / passed / failed / warning / timeout
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default='pending'
    )

    # OSS report URL
    oss_report_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Local report path (before upload to OSS)
    local_report_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False
    )

    # Error message if failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Agent raw output results
    results: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Result statistics
    result_count: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Execution configuration (for Gen mode or other dynamic configs)
    config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Relationships
    business: Mapped['Business'] = relationship(
        'Business',
        back_populates='executions'
    )
    environment: Mapped[Optional['Environment']] = relationship(
        'Environment',
        back_populates='executions'
    )

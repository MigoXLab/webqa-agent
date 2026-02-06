"""Business model."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List

from app.database import Base
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.environment import Environment
    from app.models.execution import Execution
    from app.models.scheduled_task import ScheduledTask
    from app.models.test_case import TestCase


class Business(Base):
    """Business model - represents a business/project."""

    __tablename__ = 'businesses'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False
    )

    # Relationships
    environments: Mapped[List['Environment']] = relationship(
        'Environment',
        back_populates='business',
        cascade='all, delete-orphan'
    )
    test_cases: Mapped[List['TestCase']] = relationship(
        'TestCase',
        back_populates='business',
        cascade='all, delete-orphan'
    )
    executions: Mapped[List['Execution']] = relationship(
        'Execution',
        back_populates='business',
        cascade='all, delete-orphan'
    )
    scheduled_tasks: Mapped[List['ScheduledTask']] = relationship(
        'ScheduledTask',
        back_populates='business',
        cascade='all, delete-orphan'
    )

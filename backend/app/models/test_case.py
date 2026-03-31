"""TestCase model."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.database import Base
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.business import Business


class TestCase(Base):
    """TestCase model - represents a test case in the case pool."""

    __tablename__ = 'test_cases'

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
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Whether login is required for this case
    login_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    # Default account name for this case (multi-account switching)
    account: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Test steps in JSONB format
    # Format: [{"step_type": "action/verify", "description": "...", "args": {...}}]
    steps: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list
    )

    # User-defined version label (optional)
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Snapshot configuration (optional)
    snapshot: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    use_snapshot: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Explicit sort order for user-defined ordering
    sort_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    # Status: active / draft / disabled
    status: Mapped[str] = mapped_column(
        String(20),
        default='active',
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False
    )

    # Relationships
    business: Mapped['Business'] = relationship(
        'Business',
        back_populates='test_cases'
    )

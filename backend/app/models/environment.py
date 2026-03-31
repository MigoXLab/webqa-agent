"""Environment model."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.database import Base
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.execution import Execution


class Environment(Base):
    """Environment model - represents a test environment with URL and auth config."""

    __tablename__ = 'environments'

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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Browser configuration
    browser_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict
    )

    # Ignore rules for network/console
    ignore_rules: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict
    )

    # Authentication configuration
    auth_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default='none'  # none / sso / cookies
    )
    sso_username: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sso_password: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sso_env: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default='prod'  # prod / staging / dev
    )
    cookies: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB,
        nullable=True
    )
    accounts: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False
    )

    # Relationships
    business: Mapped['Business'] = relationship(
        'Business',
        back_populates='environments'
    )
    executions: Mapped[List['Execution']] = relationship(
        'Execution',
        back_populates='environment'
    )

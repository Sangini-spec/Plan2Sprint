"""OrgJoinRequest — owner-approval gate for the canonical-match
Settings rename flow (Hotfix 86). See the migration's docstring for
the full design rationale.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, generate_cuid


# Status enum — kept as str for portability and to avoid a migration
# every time we add a state. Application-layer guards do the
# transitions.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"


class OrgJoinRequest(Base):
    __tablename__ = "org_join_requests"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )

    # Who is asking
    requester_user_id: Mapped[str] = mapped_column(
        String(25), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    requester_email: Mapped[str] = mapped_column(String, nullable=False)
    requester_full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Where they're coming from / going to
    source_org_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_org_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Snapshot of target name at request time — survives target rename
    target_org_name: Mapped[str] = mapped_column(String, nullable=False)

    # State
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING
    )

    # Audit columns
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(25), nullable=True
    )
    resolution_note: Mapped[Optional[str]] = mapped_column(String, nullable=True)

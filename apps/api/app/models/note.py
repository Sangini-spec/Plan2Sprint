"""Smart Notes — private notebook per user, attached to a project."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, generate_cuid


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(25), primary_key=True, default=generate_cuid)
    organization_id: Mapped[str] = mapped_column(
        String(25), ForeignKey("organizations.id"), name="organization_id", nullable=False
    )
    author_email: Mapped[str] = mapped_column(String, name="author_email", nullable=False, index=True)
    author_name: Mapped[Optional[str]] = mapped_column(String, name="author_name", nullable=True)
    imported_project_id: Mapped[Optional[str]] = mapped_column(
        String(25), ForeignKey("imported_projects.id"), name="imported_project_id", nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="idea", server_default="idea")
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="blue", server_default="blue")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

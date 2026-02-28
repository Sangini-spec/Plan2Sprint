from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .team_member import TeamMember
    from .work_item import WorkItem


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_id", name="uq_repositories_org_ext"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(
        String, name="external_id", nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(
        String, name="full_name", nullable=False
    )
    default_branch: Mapped[str] = mapped_column(
        String, name="default_branch", nullable=False, default="main"
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        name="updated_at",
        server_default=func.now(),
        onupdate=func.now(),
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="repositories"
    )
    pull_requests: Mapped[List["PullRequest"]] = relationship(
        back_populates="repository"
    )
    commits: Mapped[List["Commit"]] = relationship(
        back_populates="repository"
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "external_id", name="uq_pull_requests_repo_ext"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    repository_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("repositories.id"),
        name="repository_id",
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(
        String, name="external_id", nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="OPEN"
    )
    author_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("team_members.id"),
        name="author_id",
        nullable=True,
    )
    reviewers: Mapped[List[str]] = mapped_column(
        ARRAY(String), default=list
    )
    ci_status: Mapped[str] = mapped_column(
        String(50), name="ci_status", nullable=False, default="UNKNOWN"
    )
    linked_work_item_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("work_items.id"),
        name="linked_work_item_id",
        nullable=True,
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    created_external_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_external_at", nullable=False
    )
    merged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="merged_at", nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        name="updated_at",
        server_default=func.now(),
        onupdate=func.now(),
    )

    # -- relationships --
    repository: Mapped["Repository"] = relationship(
        back_populates="pull_requests"
    )
    author: Mapped[Optional["TeamMember"]] = relationship(
        back_populates="pull_requests"
    )
    linked_work_item: Mapped[Optional["WorkItem"]] = relationship(
        back_populates="pull_requests"
    )


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "sha", name="uq_commits_repo_sha"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    repository_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("repositories.id"),
        name="repository_id",
        nullable=False,
    )
    sha: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    author_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("team_members.id"),
        name="author_id",
        nullable=True,
    )
    branch: Mapped[str] = mapped_column(String, nullable=False)
    linked_ticket_ids: Mapped[List[str]] = mapped_column(
        ARRAY(String), name="linked_ticket_ids", default=list
    )
    files_changed: Mapped[int] = mapped_column(
        Integer, name="files_changed", nullable=False, default=0
    )
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="committed_at", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    repository: Mapped["Repository"] = relationship(
        back_populates="commits"
    )
    author: Mapped[Optional["TeamMember"]] = relationship(
        back_populates="commits"
    )

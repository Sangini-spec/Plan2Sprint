import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def generate_cuid() -> str:
    """Generate a CUID-like identifier (25-char hex string)."""
    return str(uuid.uuid4()).replace("-", "")[:25]


class Base(DeclarativeBase):
    pass

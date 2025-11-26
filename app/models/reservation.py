"""Reservation model."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.seat import Seat


class ReservationStatus(str, enum.Enum):
    """Reservation status enum."""

    ACTIVE = "ACTIVE"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Reservation(Base):
    """Reservation model representing a temporary seat hold."""

    __tablename__ = "reservations"

    reservation_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    seat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seats.seat_id"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.event_id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus), default=ReservationStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="reservations")

    __table_args__ = (
        Index("idx_seat_id", "seat_id"),
        Index("idx_expires_at", "expires_at"),
        Index("idx_user_id", "user_id"),
    )

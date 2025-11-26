"""Seat model."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.event import Event


class SeatType(str, enum.Enum):
    """Seat type enum."""

    REGULAR = "REGULAR"
    VIP = "VIP"
    PREMIUM = "PREMIUM"


class SeatStatus(str, enum.Enum):
    """Seat status enum."""

    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class Seat(Base):
    """Seat model representing a seat in an event venue."""

    __tablename__ = "seats"

    seat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.event_id"), nullable=False
    )
    seat_number: Mapped[str] = mapped_column(String(20), nullable=False)
    section: Mapped[str | None] = mapped_column(String(50))
    row_number: Mapped[str | None] = mapped_column(String(10))
    seat_type: Mapped[SeatType] = mapped_column(Enum(SeatType), default=SeatType.REGULAR)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[SeatStatus] = mapped_column(Enum(SeatStatus), default=SeatStatus.AVAILABLE)
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_by: Mapped[str | None] = mapped_column(String(50))
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime)
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.booking_id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="seats")
    booking: Mapped["Booking | None"] = relationship("Booking", back_populates="booked_seats")

    __table_args__ = (
        UniqueConstraint("event_id", "seat_number", name="uk_event_seat"),
        Index("idx_event_status", "event_id", "status"),
        Index("idx_reserved_until", "reserved_until"),
    )

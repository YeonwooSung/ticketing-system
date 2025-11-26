"""Event model."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.reservation import Reservation
    from app.models.seat import Seat


class EventStatus(str, enum.Enum):
    """Event status enum."""

    UPCOMING = "UPCOMING"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    CANCELLED = "CANCELLED"


class Event(Base):
    """Event model representing a ticketed event."""

    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    venue_name: Mapped[str | None] = mapped_column(String(255))
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    available_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus), default=EventStatus.UPCOMING
    )
    sale_start_time: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # Relationships
    seats: Mapped[list["Seat"]] = relationship("Seat", back_populates="event")
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="event")
    reservations: Mapped[list["Reservation"]] = relationship(
        "Reservation", back_populates="event"
    )

    __table_args__ = (
        Index("idx_sale_start_time", "sale_start_time"),
        Index("idx_status", "status"),
    )

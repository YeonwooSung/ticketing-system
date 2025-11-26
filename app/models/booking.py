"""Booking models."""

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
    from app.models.event import Event
    from app.models.seat import Seat


class BookingStatus(str, enum.Enum):
    """Booking status enum."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PaymentStatus(str, enum.Enum):
    """Payment status enum."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Booking(Base):
    """Booking model representing a confirmed ticket booking."""

    __tablename__ = "bookings"

    booking_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.event_id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus), default=BookingStatus.PENDING
    )
    payment_id: Mapped[str | None] = mapped_column(String(100))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.PENDING
    )
    booking_reference: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="bookings")
    booking_seats: Mapped[list["BookingSeat"]] = relationship(
        "BookingSeat", back_populates="booking", cascade="all, delete-orphan"
    )
    booked_seats: Mapped[list["Seat"]] = relationship("Seat", back_populates="booking")

    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_booking_reference", "booking_reference"),
        Index("idx_status", "status"),
    )


class BookingSeat(Base):
    """BookingSeat model representing seats in a booking."""

    __tablename__ = "booking_seats"

    booking_seat_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.booking_id"), nullable=False
    )
    seat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seats.seat_id"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Relationships
    booking: Mapped["Booking"] = relationship("Booking", back_populates="booking_seats")

    __table_args__ = (
        UniqueConstraint("booking_id", "seat_id", name="uk_booking_seat"),
        Index("idx_seat_id", "seat_id"),
    )

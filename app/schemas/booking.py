"""Booking schemas."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field

from app.schemas.common import BaseSchema
from app.schemas.seat import SeatResponse


class BookingStatus(str, Enum):
    """Booking status enum."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PaymentStatus(str, Enum):
    """Payment status enum."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class BookingCreate(BaseSchema):
    """Schema for creating a booking from reservations."""

    event_id: int
    user_id: str = Field(..., min_length=1, max_length=50)
    seat_ids: list[int] = Field(..., min_length=1, max_length=10)


class BookingResponse(BaseSchema):
    """Schema for booking response."""

    booking_id: int
    event_id: int
    user_id: str
    total_amount: Decimal
    status: BookingStatus
    payment_status: PaymentStatus
    booking_reference: str
    created_at: datetime
    confirmed_at: datetime | None = None
    seats: list[SeatResponse] = []


class BookingDetailResponse(BookingResponse):
    """Detailed booking response."""

    event_name: str | None = None
    venue_name: str | None = None
    event_date: datetime | None = None


class PaymentConfirmRequest(BaseSchema):
    """Schema for confirming payment."""

    booking_id: int
    payment_id: str = Field(..., min_length=1, max_length=100)


class BookingCancelRequest(BaseSchema):
    """Schema for cancelling a booking."""

    reason: str | None = Field(None, max_length=500)

"""Seat schemas."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field

from app.schemas.common import BaseSchema


class SeatType(str, Enum):
    """Seat type enum."""

    REGULAR = "REGULAR"
    VIP = "VIP"
    PREMIUM = "PREMIUM"


class SeatStatus(str, Enum):
    """Seat status enum."""

    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class SeatCreate(BaseSchema):
    """Schema for creating a seat."""

    seat_number: str = Field(..., min_length=1, max_length=20)
    section: str | None = Field(None, max_length=50)
    row_number: str | None = Field(None, max_length=10)
    seat_type: SeatType = SeatType.REGULAR
    price: Decimal = Field(..., gt=0)


class SeatBulkCreate(BaseSchema):
    """Schema for bulk seat creation."""

    event_id: int
    seats: list[SeatCreate]


class SeatResponse(BaseSchema):
    """Schema for seat response."""

    seat_id: int
    event_id: int
    seat_number: str
    section: str | None
    row_number: str | None
    seat_type: SeatType
    price: Decimal
    status: SeatStatus
    reserved_until: datetime | None = None
    created_at: datetime


class SeatAvailabilityResponse(BaseSchema):
    """Schema for seat availability check."""

    seat_id: int
    seat_number: str
    section: str | None
    seat_type: SeatType
    price: Decimal
    is_available: bool
    status: SeatStatus

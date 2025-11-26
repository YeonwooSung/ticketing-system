"""Event schemas."""

from datetime import datetime
from enum import Enum

from pydantic import Field

from app.schemas.common import BaseSchema


class EventStatus(str, Enum):
    """Event status enum."""

    UPCOMING = "UPCOMING"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    CANCELLED = "CANCELLED"


class EventCreate(BaseSchema):
    """Schema for creating an event."""

    event_name: str = Field(..., min_length=1, max_length=255)
    event_date: datetime
    venue_name: str | None = Field(None, max_length=255)
    total_seats: int = Field(..., gt=0)
    sale_start_time: datetime | None = None


class EventUpdate(BaseSchema):
    """Schema for updating an event."""

    event_name: str | None = Field(None, min_length=1, max_length=255)
    event_date: datetime | None = None
    venue_name: str | None = Field(None, max_length=255)
    status: EventStatus | None = None
    sale_start_time: datetime | None = None


class EventResponse(BaseSchema):
    """Schema for event response."""

    event_id: int
    event_name: str
    event_date: datetime
    venue_name: str | None
    total_seats: int
    available_seats: int
    status: EventStatus
    sale_start_time: datetime | None
    created_at: datetime


class EventDetailResponse(EventResponse):
    """Schema for detailed event response with seat info."""

    available_seat_count: int = 0
    reserved_seat_count: int = 0
    booked_seat_count: int = 0

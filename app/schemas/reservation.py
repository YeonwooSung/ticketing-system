"""Reservation schemas."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import BaseSchema
from app.schemas.seat import SeatResponse


class ReservationCreate(BaseSchema):
    """Schema for creating a reservation."""

    event_id: int
    seat_ids: list[int] = Field(..., min_length=1, max_length=10)
    user_id: str = Field(..., min_length=1, max_length=50)
    session_id: str | None = Field(None, max_length=100)


class ReservationResponse(BaseSchema):
    """Schema for reservation response."""

    reservation_id: int
    event_id: int
    user_id: str
    session_id: str | None
    expires_at: datetime
    status: str
    created_at: datetime
    seats: list[SeatResponse] = []


class ReservationBatchResponse(BaseSchema):
    """Schema for batch reservation response."""

    reservations: list[ReservationResponse]
    total_amount: float
    expires_at: datetime


class ReservationExtendRequest(BaseSchema):
    """Schema for extending reservation."""

    additional_minutes: int = Field(default=5, ge=1, le=15)


class ReservationCancelRequest(BaseSchema):
    """Schema for cancelling reservations."""

    reservation_ids: list[int] = Field(..., min_length=1)

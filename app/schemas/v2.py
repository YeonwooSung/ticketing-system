"""
v2 API Schemas.

Extended schemas for queue-based ticketing system.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field

from app.schemas.common import BaseSchema


class QueuePriority(str, Enum):
    """Queue priority levels."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class RequestStatus(str, Enum):
    """Request processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Reservation Schemas
class QueuedReservationRequest(BaseSchema):
    """Request to queue a reservation."""

    event_id: int
    seat_ids: list[int] = Field(..., min_length=1, max_length=10)
    user_id: str = Field(..., min_length=1, max_length=50)
    session_id: str | None = Field(None, max_length=100)
    priority: QueuePriority = QueuePriority.NORMAL


class QueuedReservationResponse(BaseSchema):
    """Response after queuing a reservation."""

    success: bool
    request_id: str
    status: RequestStatus
    message: str | None = None
    estimated_wait_time: int | None = None  # seconds
    queue_position: int | None = None


class RequestStatusResponse(BaseSchema):
    """Status of a queued request."""

    request_id: str
    status: RequestStatus
    message: str | None = None
    result: dict | None = None
    created_at: datetime | None = None
    processed_at: datetime | None = None


class ReservationResultData(BaseSchema):
    """Data returned when reservation is successful."""

    reservation_ids: list[int]
    total_amount: Decimal
    expires_at: datetime


# Queue Statistics
class QueuePriorityStats(BaseSchema):
    """Statistics for a queue priority level."""

    length: int
    pending: int


class QueueStatsResponse(BaseSchema):
    """Queue statistics response."""

    event_id: int
    high: QueuePriorityStats
    normal: QueuePriorityStats
    low: QueuePriorityStats
    total_pending: int
    estimated_wait_time: int  # seconds


# Booking Schemas (v2 specific)
class QueuedBookingRequest(BaseSchema):
    """Request to create booking from queued reservation."""

    event_id: int
    user_id: str = Field(..., min_length=1, max_length=50)
    seat_ids: list[int] = Field(..., min_length=1, max_length=10)
    priority: QueuePriority = QueuePriority.NORMAL


class QueuedBookingResponse(BaseSchema):
    """Response after queuing a booking request."""

    success: bool
    request_id: str
    status: RequestStatus
    message: str | None = None


# WebSocket Messages
class WSMessageType(str, Enum):
    """WebSocket message types."""

    STATUS_UPDATE = "status_update"
    QUEUE_POSITION = "queue_position"
    RESERVATION_COMPLETE = "reservation_complete"
    RESERVATION_FAILED = "reservation_failed"
    ERROR = "error"


class WSMessage(BaseSchema):
    """WebSocket message."""

    type: WSMessageType
    request_id: str | None = None
    data: dict = {}
    timestamp: datetime = Field(default_factory=datetime.now)

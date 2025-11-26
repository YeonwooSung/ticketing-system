"""API dependencies."""

from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.redis_client import get_redis
from app.services.booking_service import BookingService
from app.services.event_service import EventService
from app.services.reservation_service import ReservationService
from app.services.seat_service import SeatService

# Type aliases
DBSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[redis.Redis, Depends(get_redis)]


async def get_current_user_id(
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """
    Get current user ID from header.
    In a real application, this would verify JWT tokens, etc.
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-ID header is required",
        )
    return x_user_id


CurrentUser = Annotated[str, Depends(get_current_user_id)]


def get_event_service(db: DBSession) -> EventService:
    """Get event service."""
    return EventService(db)


def get_seat_service(db: DBSession) -> SeatService:
    """Get seat service."""
    return SeatService(db)


def get_reservation_service(
    db: DBSession,
    redis_client: RedisClient,
) -> ReservationService:
    """Get reservation service."""
    return ReservationService(db, redis_client)


def get_booking_service(
    db: DBSession,
    redis_client: RedisClient,
) -> BookingService:
    """Get booking service."""
    return BookingService(db, redis_client)


# Annotated dependencies
EventServiceDep = Annotated[EventService, Depends(get_event_service)]
SeatServiceDep = Annotated[SeatService, Depends(get_seat_service)]
ReservationServiceDep = Annotated[ReservationService, Depends(get_reservation_service)]
BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]

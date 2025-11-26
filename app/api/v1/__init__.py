"""API v1 routers package."""

from app.api.v1.bookings import router as bookings_router
from app.api.v1.events import router as events_router
from app.api.v1.reservations import router as reservations_router
from app.api.v1.seats import router as seats_router

__all__ = [
    "events_router",
    "seats_router",
    "reservations_router",
    "bookings_router",
]

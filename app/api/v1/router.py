"""API v1 main router."""

from fastapi import APIRouter

from app.api.v1.bookings import router as bookings_router
from app.api.v1.events import router as events_router
from app.api.v1.reservations import router as reservations_router
from app.api.v1.seats import router as seats_router

router = APIRouter(prefix="/v1")

router.include_router(events_router, prefix="/events", tags=["Events"])
router.include_router(seats_router, prefix="/seats", tags=["Seats"])
router.include_router(reservations_router, prefix="/reservations", tags=["Reservations"])
router.include_router(bookings_router, prefix="/bookings", tags=["Bookings"])

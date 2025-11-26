"""v2 API router."""

from fastapi import APIRouter

from app.api.v2.queue import router as queue_router
from app.api.v2.reservations import router as reservations_router
from app.api.v2.websocket import router as ws_router

router = APIRouter(prefix="/v2")

router.include_router(reservations_router, prefix="/reservations", tags=["v2 - Reservations"])
router.include_router(queue_router, prefix="/queue", tags=["v2 - Queue"])
router.include_router(ws_router, prefix="/ws", tags=["v2 - WebSocket"])

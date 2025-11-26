"""
Queue-based reservation service for v2 API.

Processes ticket requests sequentially using Redis Streams,
ensuring fair ordering and preventing overselling.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db_context
from app.models.reservation import Reservation, ReservationStatus
from app.models.seat import Seat, SeatStatus
from app.queue import QueuePriority, QueueWorker, TicketingQueue, TicketRequest
from app.redis_client import get_redis

settings = get_settings()
logger = logging.getLogger(__name__)


class QueuedReservationService:
    """
    Queue-based reservation service.
    
    Unlike v1's distributed lock approach, v2 uses a queue-based system
    that processes requests in order, providing fair access during
    high-demand periods.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.queue = TicketingQueue(redis_client)
        self._workers: dict[int, QueueWorker] = {}

    async def initialize(self) -> None:
        """Initialize the service."""
        await self.queue.initialize()

    async def submit_reservation(
        self,
        request_id: str,
        event_id: int,
        user_id: str,
        seat_ids: list[int],
        priority: QueuePriority = QueuePriority.NORMAL,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit a reservation request to the queue.
        
        Returns immediately with a request ID that can be used
        to poll for status.
        
        Args:
            request_id: Unique request identifier
            event_id: Event ID
            user_id: User ID
            seat_ids: List of seat IDs to reserve
            priority: Queue priority
            session_id: Optional session ID
            
        Returns:
            Dict with request_id and initial status
        """
        if len(seat_ids) > settings.MAX_SEATS_PER_BOOKING:
            return {
                "success": False,
                "request_id": request_id,
                "status": "rejected",
                "message": f"Cannot reserve more than {settings.MAX_SEATS_PER_BOOKING} seats",
            }

        # Create request
        request = TicketRequest(
            request_id=request_id,
            event_id=event_id,
            user_id=user_id,
            seat_ids=seat_ids,
            priority=priority,
            session_id=session_id,
            timestamp=datetime.now(),
        )

        # Enqueue
        message_id = await self.queue.enqueue(request)

        # Ensure worker is running for this event
        await self._ensure_worker(event_id)

        return {
            "success": True,
            "request_id": request_id,
            "status": "pending",
            "message": "Request queued for processing",
            "queue_message_id": message_id,
        }

    async def get_request_status(self, request_id: str) -> dict[str, Any] | None:
        """Get status of a reservation request."""
        status = await self.queue.get_status(request_id)
        if not status:
            return None

        result = {
            "request_id": status.request_id,
            "status": status.status,
            "message": status.message,
        }

        # If completed, include result
        if status.status in ("completed", "failed"):
            queue_result = await self.queue.get_result(request_id)
            if queue_result:
                result["result"] = queue_result

        return result

    async def get_queue_stats(self, event_id: int) -> dict[str, Any]:
        """Get queue statistics for an event."""
        return await self.queue.get_queue_stats(event_id)

    async def _ensure_worker(self, event_id: int) -> None:
        """Ensure a worker is running for the event."""
        if event_id in self._workers:
            return

        worker = QueueWorker(
            queue=self.queue,
            event_id=event_id,
            consumer_name=f"worker-{event_id}-1",
            process_callback=self._process_reservation,
        )
        self._workers[event_id] = worker
        await worker.start()

    async def _process_reservation(
        self,
        request: TicketRequest,
    ) -> dict[str, Any]:
        """
        Process a reservation request.
        
        This is called by the worker and runs within the queue's
        sequential processing context.
        """
        async with get_db_context() as db:
            try:
                reservations, total_amount = await self._do_reserve(
                    db,
                    request.event_id,
                    request.seat_ids,
                    request.user_id,
                    request.session_id,
                )

                return {
                    "success": True,
                    "message": "Reservation successful",
                    "data": {
                        "reservation_ids": [r.reservation_id for r in reservations],
                        "total_amount": str(total_amount),
                        "expires_at": reservations[0].expires_at.isoformat()
                        if reservations
                        else None,
                    },
                }

            except Exception as e:
                logger.error(f"Reservation failed: {e}")
                return {
                    "success": False,
                    "message": str(e),
                    "data": {},
                }

    async def _do_reserve(
        self,
        db: AsyncSession,
        event_id: int,
        seat_ids: list[int],
        user_id: str,
        session_id: str | None,
    ) -> tuple[list[Reservation], Decimal]:
        """
        Perform the actual reservation.
        
        Since this runs in a sequential worker, we don't need
        distributed locks - the queue ensures only one request
        is processed at a time per event.
        """
        # Get seats with database lock (FOR UPDATE)
        result = await db.execute(
            select(Seat)
            .where(Seat.seat_id.in_(seat_ids))
            .order_by(Seat.seat_id)
            .with_for_update()
        )
        seats = list(result.scalars().all())

        # Validate seats
        if len(seats) != len(seat_ids):
            raise ValueError("One or more seats not found")

        for seat in seats:
            if seat.event_id != event_id:
                raise ValueError(f"Seat {seat.seat_id} does not belong to event {event_id}")

        # Check availability
        unavailable = [s for s in seats if s.status != SeatStatus.AVAILABLE]
        if unavailable:
            seat_numbers = [s.seat_number for s in unavailable]
            raise ValueError(f"Seats not available: {', '.join(seat_numbers)}")

        # Calculate expiration
        expires_at = datetime.now() + timedelta(
            seconds=settings.RESERVATION_TIMEOUT_SECONDS
        )

        # Create reservations
        reservations = []
        total_amount = Decimal("0")

        for seat in seats:
            seat.status = SeatStatus.RESERVED
            seat.reserved_by = user_id
            seat.reserved_until = expires_at
            seat.version += 1

            reservation = Reservation(
                seat_id=seat.seat_id,
                event_id=event_id,
                user_id=user_id,
                session_id=session_id,
                expires_at=expires_at,
                status=ReservationStatus.ACTIVE,
            )
            db.add(reservation)
            reservations.append(reservation)
            total_amount += seat.price

        await db.commit()

        for reservation in reservations:
            await db.refresh(reservation)

        return reservations, total_amount

    async def stop_all_workers(self) -> None:
        """Stop all workers."""
        for worker in self._workers.values():
            await worker.stop()
        self._workers.clear()


# Global instance
_queued_service: QueuedReservationService | None = None


async def get_queued_reservation_service() -> QueuedReservationService:
    """Get the queued reservation service instance."""
    global _queued_service
    if _queued_service is None:
        redis_client = await get_redis()
        _queued_service = QueuedReservationService(redis_client)
        await _queued_service.initialize()
    return _queued_service


async def shutdown_queued_service() -> None:
    """Shutdown the queued reservation service."""
    global _queued_service
    if _queued_service is not None:
        await _queued_service.stop_all_workers()
        _queued_service = None

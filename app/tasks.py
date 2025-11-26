"""Background tasks for the ticketing system."""

import asyncio
import logging

from app.database import get_db_context
from app.redis_client import get_redis
from app.services.reservation_service import ReservationService

logger = logging.getLogger(__name__)


async def cleanup_expired_reservations() -> None:
    """
    Background task to cleanup expired reservations.
    
    Runs periodically to:
    1. Mark expired reservations as EXPIRED
    2. Release associated seats back to AVAILABLE
    """
    logger.info("Starting expired reservation cleanup task")

    while True:
        try:
            async with get_db_context() as db:
                redis_client = await get_redis()
                service = ReservationService(db, redis_client)
                expired_count = await service.expire_old_reservations()

                if expired_count > 0:
                    logger.info(f"Cleaned up {expired_count} expired reservations")

        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

        # Run every 30 seconds
        await asyncio.sleep(30)


class BackgroundTaskManager:
    """Manager for background tasks."""

    def __init__(self):
        self.tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all background tasks."""
        self.tasks.append(
            asyncio.create_task(cleanup_expired_reservations())
        )
        logger.info("Background tasks started")

    async def stop(self) -> None:
        """Stop all background tasks."""
        for task in self.tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.tasks.clear()
        logger.info("Background tasks stopped")


# Global instance
background_tasks = BackgroundTaskManager()

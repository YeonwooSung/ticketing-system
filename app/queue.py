"""
Queue-based ticketing system for v2 API.

Uses Redis Streams for ordered message processing with:
- FIFO ordering for fair ticket allocation
- Priority queuing for VIP users
- Consumer groups for scalable processing
"""

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any

import redis.asyncio as redis
from pydantic import BaseModel

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class QueuePriority(str, Enum):
    """Queue priority levels."""

    HIGH = "high"  # VIP users, premium members
    NORMAL = "normal"  # Regular users
    LOW = "low"  # Batch/background operations


class TicketRequest(BaseModel):
    """Ticket reservation request message."""

    request_id: str
    event_id: int
    user_id: str
    seat_ids: list[int]
    priority: QueuePriority = QueuePriority.NORMAL
    session_id: str | None = None
    timestamp: datetime
    metadata: dict[str, Any] = {}


class TicketResponse(BaseModel):
    """Ticket reservation response."""

    request_id: str
    status: str  # "pending", "processing", "completed", "failed"
    message: str | None = None
    data: dict[str, Any] = {}
    processed_at: datetime | None = None


class TicketingQueue:
    """
    Redis Streams-based ticketing queue.
    
    Provides ordered processing of ticket requests with:
    - Multiple priority levels
    - Consumer groups for horizontal scaling
    - Request status tracking
    - Dead letter queue for failed requests
    """

    # Stream names
    STREAM_PREFIX = "ticketing:queue"
    STATUS_PREFIX = "ticketing:status"
    RESULT_PREFIX = "ticketing:result"
    DLQ_STREAM = "ticketing:dlq"

    # Consumer group
    CONSUMER_GROUP = "ticketing-workers"

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._initialized = False

    def _get_stream_name(self, event_id: int, priority: QueuePriority) -> str:
        """Get stream name for event and priority."""
        return f"{self.STREAM_PREFIX}:{event_id}:{priority.value}"

    def _get_status_key(self, request_id: str) -> str:
        """Get status key for request."""
        return f"{self.STATUS_PREFIX}:{request_id}"

    def _get_result_key(self, request_id: str) -> str:
        """Get result key for request."""
        return f"{self.RESULT_PREFIX}:{request_id}"

    async def initialize(self) -> None:
        """Initialize consumer groups for streams."""
        if self._initialized:
            return
        self._initialized = True
        logger.info("Ticketing queue initialized")

    async def ensure_consumer_group(self, stream_name: str) -> None:
        """Ensure consumer group exists for stream."""
        try:
            await self.redis.xgroup_create(
                stream_name,
                self.CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def enqueue(self, request: TicketRequest) -> str:
        """
        Add ticket request to queue.
        
        Returns:
            Message ID from Redis Stream
        """
        stream_name = self._get_stream_name(request.event_id, request.priority)

        # Ensure consumer group exists
        await self.ensure_consumer_group(stream_name)

        # Prepare message
        message = {
            "request_id": request.request_id,
            "event_id": str(request.event_id),
            "user_id": request.user_id,
            "seat_ids": json.dumps(request.seat_ids),
            "priority": request.priority.value,
            "session_id": request.session_id or "",
            "timestamp": request.timestamp.isoformat(),
            "metadata": json.dumps(request.metadata),
        }

        # Add to stream
        message_id = await self.redis.xadd(stream_name, message)

        # Set initial status
        await self._set_status(
            request.request_id,
            "pending",
            message="Request queued for processing",
            queue_position=await self._get_queue_position(stream_name, message_id),
        )

        logger.info(f"Enqueued request {request.request_id} to {stream_name}")
        return message_id

    async def _get_queue_position(self, stream_name: str, message_id: str) -> int:
        """Get approximate position in queue."""
        try:
            info = await self.redis.xinfo_stream(stream_name)
            return info.get("length", 0)
        except Exception:
            return -1

    async def _set_status(
        self,
        request_id: str,
        status: str,
        message: str | None = None,
        **extra: Any,
    ) -> None:
        """Set request status."""
        status_key = self._get_status_key(request_id)
        data = {
            "status": status,
            "message": message or "",
            "updated_at": datetime.now().isoformat(),
            **{k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in extra.items()},
        }
        await self.redis.hset(status_key, mapping=data)
        # Set expiration (24 hours)
        await self.redis.expire(status_key, 86400)

    async def get_status(self, request_id: str) -> TicketResponse | None:
        """Get request status."""
        status_key = self._get_status_key(request_id)
        data = await self.redis.hgetall(status_key)

        if not data:
            return None

        return TicketResponse(
            request_id=request_id,
            status=data.get("status", "unknown"),
            message=data.get("message"),
            data={
                k: v
                for k, v in data.items()
                if k not in ("status", "message", "updated_at")
            },
            processed_at=(
                datetime.fromisoformat(data["updated_at"])
                if "updated_at" in data
                else None
            ),
        )

    async def set_result(
        self,
        request_id: str,
        success: bool,
        data: dict[str, Any],
        message: str | None = None,
    ) -> None:
        """Set request result."""
        result_key = self._get_result_key(request_id)
        result = {
            "success": "true" if success else "false",
            "message": message or "",
            "data": json.dumps(data),
            "completed_at": datetime.now().isoformat(),
        }
        await self.redis.hset(result_key, mapping=result)
        await self.redis.expire(result_key, 86400)

        # Update status
        await self._set_status(
            request_id,
            "completed" if success else "failed",
            message=message,
        )

    async def get_result(self, request_id: str) -> dict[str, Any] | None:
        """Get request result."""
        result_key = self._get_result_key(request_id)
        data = await self.redis.hgetall(result_key)

        if not data:
            return None

        return {
            "success": data.get("success") == "true",
            "message": data.get("message"),
            "data": json.loads(data.get("data", "{}")),
            "completed_at": data.get("completed_at"),
        }

    async def dequeue(
        self,
        event_id: int,
        consumer_name: str,
        count: int = 1,
        block_ms: int = 5000,
    ) -> list[tuple[str, TicketRequest]]:
        """
        Dequeue ticket requests for processing.
        
        Processes high priority first, then normal, then low.
        
        Returns:
            List of (message_id, request) tuples
        """
        results = []

        # Process by priority order
        for priority in [QueuePriority.HIGH, QueuePriority.NORMAL, QueuePriority.LOW]:
            if len(results) >= count:
                break

            stream_name = self._get_stream_name(event_id, priority)
            remaining = count - len(results)

            try:
                # Ensure consumer group exists
                await self.ensure_consumer_group(stream_name)

                # Read from stream
                messages = await self.redis.xreadgroup(
                    self.CONSUMER_GROUP,
                    consumer_name,
                    {stream_name: ">"},
                    count=remaining,
                    block=block_ms if not results else 0,
                )

                for stream, stream_messages in messages:
                    for message_id, data in stream_messages:
                        request = TicketRequest(
                            request_id=data["request_id"],
                            event_id=int(data["event_id"]),
                            user_id=data["user_id"],
                            seat_ids=json.loads(data["seat_ids"]),
                            priority=QueuePriority(data["priority"]),
                            session_id=data["session_id"] or None,
                            timestamp=datetime.fromisoformat(data["timestamp"]),
                            metadata=json.loads(data.get("metadata", "{}")),
                        )

                        # Update status to processing
                        await self._set_status(
                            request.request_id,
                            "processing",
                            message="Request is being processed",
                        )

                        results.append((message_id, request))

            except redis.ResponseError as e:
                if "NOGROUP" not in str(e):
                    logger.error(f"Error reading from stream {stream_name}: {e}")

        return results

    async def acknowledge(
        self,
        event_id: int,
        priority: QueuePriority,
        message_id: str,
    ) -> None:
        """Acknowledge message processing completion."""
        stream_name = self._get_stream_name(event_id, priority)
        await self.redis.xack(stream_name, self.CONSUMER_GROUP, message_id)

    async def move_to_dlq(
        self,
        request: TicketRequest,
        error: str,
    ) -> None:
        """Move failed request to dead letter queue."""
        message = {
            "request_id": request.request_id,
            "event_id": str(request.event_id),
            "user_id": request.user_id,
            "seat_ids": json.dumps(request.seat_ids),
            "priority": request.priority.value,
            "error": error,
            "failed_at": datetime.now().isoformat(),
        }
        await self.redis.xadd(self.DLQ_STREAM, message)

    async def get_queue_stats(self, event_id: int) -> dict[str, Any]:
        """Get queue statistics for an event."""
        stats = {}

        for priority in QueuePriority:
            stream_name = self._get_stream_name(event_id, priority)
            try:
                info = await self.redis.xinfo_stream(stream_name)
                pending = await self.redis.xpending(stream_name, self.CONSUMER_GROUP)

                stats[priority.value] = {
                    "length": info.get("length", 0),
                    "pending": pending.get("pending", 0) if pending else 0,
                    "first_entry": info.get("first-entry"),
                    "last_entry": info.get("last-entry"),
                }
            except redis.ResponseError:
                stats[priority.value] = {
                    "length": 0,
                    "pending": 0,
                }

        return stats


class QueueWorker:
    """
    Worker for processing ticket requests from queue.
    
    Runs as a background task and processes requests sequentially.
    """

    def __init__(
        self,
        queue: TicketingQueue,
        event_id: int,
        consumer_name: str,
        process_callback,
    ):
        self.queue = queue
        self.event_id = event_id
        self.consumer_name = consumer_name
        self.process_callback = process_callback
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the worker."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(f"Queue worker started for event {self.event_id}")

    async def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Queue worker stopped for event {self.event_id}")

    async def _run(self) -> None:
        """Main worker loop."""
        while self._running:
            try:
                # Dequeue requests
                requests = await self.queue.dequeue(
                    self.event_id,
                    self.consumer_name,
                    count=1,
                    block_ms=5000,
                )

                for message_id, request in requests:
                    try:
                        # Process request
                        result = await self.process_callback(request)

                        # Set result
                        await self.queue.set_result(
                            request.request_id,
                            success=result.get("success", False),
                            data=result.get("data", {}),
                            message=result.get("message"),
                        )

                        # Acknowledge
                        await self.queue.acknowledge(
                            self.event_id,
                            request.priority,
                            message_id,
                        )

                    except Exception as e:
                        logger.error(
                            f"Error processing request {request.request_id}: {e}"
                        )
                        await self.queue.move_to_dlq(request, str(e))
                        await self.queue.set_result(
                            request.request_id,
                            success=False,
                            data={},
                            message=f"Processing failed: {e}",
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(1)

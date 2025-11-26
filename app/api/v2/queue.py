"""v2 Queue Management API."""

from fastapi import APIRouter, HTTPException, status

from app.api.v2.dependencies import QueuedServiceDep
from app.schemas.v2 import QueuePriorityStats, QueueStatsResponse

router = APIRouter()


@router.get(
    "/stats/{event_id}",
    response_model=QueueStatsResponse,
    summary="Get queue statistics",
)
async def get_queue_stats(
    event_id: int,
    queued_service: QueuedServiceDep,
) -> QueueStatsResponse:
    """
    Get queue statistics for an event.
    
    Shows the current queue length and processing status.
    Useful for displaying wait times to users.
    """
    stats = await queued_service.get_queue_stats(event_id)

    high = stats.get("high", {})
    normal = stats.get("normal", {})
    low = stats.get("low", {})

    total_pending = (
        high.get("length", 0)
        + high.get("pending", 0)
        + normal.get("length", 0)
        + normal.get("pending", 0)
        + low.get("length", 0)
        + low.get("pending", 0)
    )

    # Estimate wait time (~500ms per request)
    estimated_wait = int(total_pending * 0.5)

    return QueueStatsResponse(
        event_id=event_id,
        high=QueuePriorityStats(
            length=high.get("length", 0),
            pending=high.get("pending", 0),
        ),
        normal=QueuePriorityStats(
            length=normal.get("length", 0),
            pending=normal.get("pending", 0),
        ),
        low=QueuePriorityStats(
            length=low.get("length", 0),
            pending=low.get("pending", 0),
        ),
        total_pending=total_pending,
        estimated_wait_time=estimated_wait,
    )


@router.get(
    "/health",
    summary="Queue health check",
)
async def queue_health(
    queued_service: QueuedServiceDep,
) -> dict:
    """
    Check queue system health.
    
    Verifies Redis connectivity and queue functionality.
    """
    try:
        # Simple ping to verify Redis connection
        await queued_service.redis.ping()
        return {
            "status": "healthy",
            "redis": "connected",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Queue system unhealthy: {e}",
        )

"""v2 Queue-based Reservations API."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from ulid import ULID

from app.api.v2.dependencies import CurrentUser, QueuedServiceDep, UserPriority
from app.queue import QueuePriority
from app.schemas.v2 import (
    QueuedReservationRequest,
    QueuedReservationResponse,
    RequestStatus,
    RequestStatusResponse,
)

router = APIRouter()


@router.post(
    "",
    response_model=QueuedReservationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a reservation request",
)
async def queue_reservation(
    request_data: QueuedReservationRequest,
    current_user: CurrentUser,
    user_priority: UserPriority,
    queued_service: QueuedServiceDep,
) -> QueuedReservationResponse:
    """
    Submit a reservation request to the queue.
    
    Unlike v1 which processes immediately with distributed locks,
    v2 queues requests and processes them in order.
    
    This provides:
    - Fair ordering during high-demand periods
    - Priority support for VIP users
    - Non-blocking request submission
    
    Returns a request_id that can be used to poll for status.
    """
    if request_data.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create reservation for another user",
        )

    # Generate request ID
    request_id = str(ULID())

    # Determine priority
    if request_data.priority == QueuePriority.HIGH:
        # Only allow if user has VIP status
        if user_priority != "high":
            priority = QueuePriority.NORMAL
        else:
            priority = QueuePriority.HIGH
    else:
        priority = QueuePriority(request_data.priority.value)

    # Submit to queue
    result = await queued_service.submit_reservation(
        request_id=request_id,
        event_id=request_data.event_id,
        user_id=current_user,
        seat_ids=request_data.seat_ids,
        priority=priority,
        session_id=request_data.session_id,
    )

    if not result["success"]:
        return QueuedReservationResponse(
            success=False,
            request_id=request_id,
            status=RequestStatus.FAILED,
            message=result.get("message"),
        )

    # Get queue stats for estimated wait time
    stats = await queued_service.get_queue_stats(request_data.event_id)
    total_pending = sum(
        s.get("length", 0) + s.get("pending", 0)
        for s in stats.values()
    )
    
    # Estimate ~500ms per request
    estimated_wait = int(total_pending * 0.5)

    return QueuedReservationResponse(
        success=True,
        request_id=request_id,
        status=RequestStatus.PENDING,
        message="Request queued for processing",
        estimated_wait_time=estimated_wait,
        queue_position=total_pending,
    )


@router.get(
    "/{request_id}",
    response_model=RequestStatusResponse,
    summary="Get reservation request status",
)
async def get_request_status(
    request_id: str,
    current_user: CurrentUser,
    queued_service: QueuedServiceDep,
) -> RequestStatusResponse:
    """
    Get the status of a queued reservation request.
    
    Poll this endpoint to check if your reservation has been processed.
    """
    result = await queued_service.get_request_status(request_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )

    return RequestStatusResponse(
        request_id=result["request_id"],
        status=RequestStatus(result["status"]),
        message=result.get("message"),
        result=result.get("result"),
    )


@router.delete(
    "/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a pending reservation request",
)
async def cancel_request(
    request_id: str,
    current_user: CurrentUser,
    queued_service: QueuedServiceDep,
) -> None:
    """
    Cancel a pending reservation request.
    
    Only works for requests that haven't started processing yet.
    """
    result = await queued_service.get_request_status(request_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )

    if result["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel request in '{result['status']}' state",
        )

    # Note: Actual cancellation from Redis Stream is complex
    # For now, we just mark it as cancelled in status
    # The worker will skip cancelled requests
    # This is a simplified implementation
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Request cancellation not yet implemented",
    )

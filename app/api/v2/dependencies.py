"""v2 API dependencies."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.services.queued_reservation_service import (
    QueuedReservationService,
    get_queued_reservation_service,
)


async def get_current_user_id(
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """Get current user ID from header."""
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-ID header is required",
        )
    return x_user_id


async def get_user_priority(
    x_user_priority: Annotated[str | None, Header()] = None,
) -> str:
    """
    Get user priority from header.
    
    In production, this would be determined by user's subscription level,
    membership status, etc.
    """
    if x_user_priority and x_user_priority.lower() in ("high", "vip", "premium"):
        return "high"
    return "normal"


CurrentUser = Annotated[str, Depends(get_current_user_id)]
UserPriority = Annotated[str, Depends(get_user_priority)]
QueuedServiceDep = Annotated[
    QueuedReservationService, Depends(get_queued_reservation_service)
]

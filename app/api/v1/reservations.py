"""Reservations API endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import (
    CurrentUser,
    ReservationServiceDep,
    SeatServiceDep,
)
from app.schemas.common import SuccessResponse
from app.schemas.reservation import (
    ReservationBatchResponse,
    ReservationCancelRequest,
    ReservationCreate,
    ReservationExtendRequest,
    ReservationResponse,
)
from app.schemas.seat import SeatResponse
from app.services.reservation_service import ReservationError

router = APIRouter()


@router.post(
    "",
    response_model=ReservationBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve seats",
)
async def reserve_seats(
    reservation_data: ReservationCreate,
    current_user: CurrentUser,
    reservation_service: ReservationServiceDep,
    seat_service: SeatServiceDep,
) -> ReservationBatchResponse:
    """
    Reserve multiple seats atomically.
    
    Uses distributed locking to ensure thread-safety.
    Reservations expire after a configurable timeout (default 10 minutes).
    """
    # Override user_id with authenticated user
    if reservation_data.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create reservation for another user",
        )

    try:
        reservations, total_amount = await reservation_service.reserve_seats(
            event_id=reservation_data.event_id,
            seat_ids=reservation_data.seat_ids,
            user_id=current_user,
            session_id=reservation_data.session_id,
        )
    except ReservationError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    # Get seat details for response
    seats = await seat_service.get_seats(reservation_data.seat_ids)
    seat_responses = [SeatResponse.model_validate(s) for s in seats]

    # Build response
    reservation_responses = []
    for i, res in enumerate(reservations):
        reservation_responses.append(
            ReservationResponse(
                reservation_id=res.reservation_id,
                event_id=res.event_id,
                user_id=res.user_id,
                session_id=res.session_id,
                expires_at=res.expires_at,
                status=res.status.value,
                created_at=res.created_at,
                seats=[seat_responses[i]] if i < len(seat_responses) else [],
            )
        )

    return ReservationBatchResponse(
        reservations=reservation_responses,
        total_amount=float(total_amount),
        expires_at=reservations[0].expires_at if reservations else None,
    )


@router.get(
    "",
    response_model=list[ReservationResponse],
    summary="Get user reservations",
)
async def get_user_reservations(
    current_user: CurrentUser,
    reservation_service: ReservationServiceDep,
    event_id: int | None = None,
    active_only: bool = True,
) -> list[ReservationResponse]:
    """Get reservations for the current user."""
    from app.models.reservation import ReservationStatus

    status_filter = ReservationStatus.ACTIVE if active_only else None

    reservations = await reservation_service.get_user_reservations(
        user_id=current_user,
        event_id=event_id,
        status=status_filter,
    )

    return [
        ReservationResponse(
            reservation_id=r.reservation_id,
            event_id=r.event_id,
            user_id=r.user_id,
            session_id=r.session_id,
            expires_at=r.expires_at,
            status=r.status.value,
            created_at=r.created_at,
            seats=[],
        )
        for r in reservations
    ]


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
    summary="Get reservation details",
)
async def get_reservation(
    reservation_id: int,
    current_user: CurrentUser,
    reservation_service: ReservationServiceDep,
    seat_service: SeatServiceDep,
) -> ReservationResponse:
    """Get reservation details."""
    reservation = await reservation_service.get_reservation(reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    if reservation.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's reservation",
        )

    # Get seat details
    seat = await seat_service.get_seat(reservation.seat_id)
    seats = [SeatResponse.model_validate(seat)] if seat else []

    return ReservationResponse(
        reservation_id=reservation.reservation_id,
        event_id=reservation.event_id,
        user_id=reservation.user_id,
        session_id=reservation.session_id,
        expires_at=reservation.expires_at,
        status=reservation.status.value,
        created_at=reservation.created_at,
        seats=seats,
    )


@router.post(
    "/{reservation_id}/extend",
    response_model=ReservationResponse,
    summary="Extend reservation",
)
async def extend_reservation(
    reservation_id: int,
    extend_data: ReservationExtendRequest,
    current_user: CurrentUser,
    reservation_service: ReservationServiceDep,
) -> ReservationResponse:
    """Extend reservation expiration time."""
    try:
        reservation = await reservation_service.extend_reservation(
            reservation_id=reservation_id,
            user_id=current_user,
            additional_minutes=extend_data.additional_minutes,
        )
    except ReservationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    return ReservationResponse(
        reservation_id=reservation.reservation_id,
        event_id=reservation.event_id,
        user_id=reservation.user_id,
        session_id=reservation.session_id,
        expires_at=reservation.expires_at,
        status=reservation.status.value,
        created_at=reservation.created_at,
        seats=[],
    )


@router.delete(
    "/{reservation_id}",
    response_model=SuccessResponse,
    summary="Cancel reservation",
)
async def cancel_reservation(
    reservation_id: int,
    current_user: CurrentUser,
    reservation_service: ReservationServiceDep,
) -> SuccessResponse:
    """Cancel a reservation."""
    try:
        success = await reservation_service.cancel_reservation(
            reservation_id=reservation_id,
            user_id=current_user,
        )
    except ReservationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    return SuccessResponse(message="Reservation cancelled successfully")


@router.post(
    "/cancel-batch",
    response_model=dict,
    summary="Cancel multiple reservations",
)
async def cancel_reservations_batch(
    cancel_data: ReservationCancelRequest,
    current_user: CurrentUser,
    reservation_service: ReservationServiceDep,
) -> dict:
    """Cancel multiple reservations at once."""
    cancelled_count = await reservation_service.cancel_reservations_batch(
        reservation_ids=cancel_data.reservation_ids,
        user_id=current_user,
    )

    return {
        "cancelled": cancelled_count,
        "requested": len(cancel_data.reservation_ids),
    }

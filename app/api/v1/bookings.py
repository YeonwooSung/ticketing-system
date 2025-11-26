"""Bookings API endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import (
    BookingServiceDep,
    CurrentUser,
    EventServiceDep,
    SeatServiceDep,
)
from app.schemas.booking import (
    BookingCancelRequest,
    BookingCreate,
    BookingDetailResponse,
    BookingResponse,
    BookingStatus,
    PaymentConfirmRequest,
    PaymentStatus,
)
from app.schemas.common import SuccessResponse
from app.schemas.seat import SeatResponse
from app.services.booking_service import BookingError

router = APIRouter()


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create booking",
)
async def create_booking(
    booking_data: BookingCreate,
    current_user: CurrentUser,
    booking_service: BookingServiceDep,
    seat_service: SeatServiceDep,
) -> BookingResponse:
    """
    Create a booking from reserved seats.
    
    The seats must already be reserved by the user.
    Uses distributed locking to ensure thread-safety.
    """
    if booking_data.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create booking for another user",
        )

    try:
        booking = await booking_service.create_booking(
            event_id=booking_data.event_id,
            user_id=current_user,
            seat_ids=booking_data.seat_ids,
        )
    except BookingError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    # Get seat details
    seats = await seat_service.get_seats(booking_data.seat_ids)
    seat_responses = [SeatResponse.model_validate(s) for s in seats]

    return BookingResponse(
        booking_id=booking.booking_id,
        event_id=booking.event_id,
        user_id=booking.user_id,
        total_amount=booking.total_amount,
        status=BookingStatus(booking.status.value),
        payment_status=PaymentStatus(booking.payment_status.value),
        booking_reference=booking.booking_reference,
        created_at=booking.created_at,
        confirmed_at=booking.confirmed_at,
        seats=seat_responses,
    )


@router.get(
    "",
    response_model=list[BookingResponse],
    summary="Get user bookings",
)
async def get_user_bookings(
    current_user: CurrentUser,
    booking_service: BookingServiceDep,
    status_filter: BookingStatus | None = None,
) -> list[BookingResponse]:
    """Get all bookings for the current user."""
    from app.models.booking import BookingStatus as ModelBookingStatus

    db_status = None
    if status_filter:
        db_status = ModelBookingStatus(status_filter.value)

    bookings = await booking_service.get_user_bookings(
        user_id=current_user,
        status=db_status,
    )

    return [
        BookingResponse(
            booking_id=b.booking_id,
            event_id=b.event_id,
            user_id=b.user_id,
            total_amount=b.total_amount,
            status=BookingStatus(b.status.value),
            payment_status=PaymentStatus(b.payment_status.value),
            booking_reference=b.booking_reference,
            created_at=b.created_at,
            confirmed_at=b.confirmed_at,
            seats=[],
        )
        for b in bookings
    ]


@router.get(
    "/{booking_id}",
    response_model=BookingDetailResponse,
    summary="Get booking details",
)
async def get_booking(
    booking_id: int,
    current_user: CurrentUser,
    booking_service: BookingServiceDep,
    event_service: EventServiceDep,
) -> BookingDetailResponse:
    """Get booking details with seats."""
    result = await booking_service.get_booking_with_seats(booking_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    booking = result["booking"]
    seats = result["seats"]

    if booking.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's booking",
        )

    # Get event details
    event = await event_service.get_event(booking.event_id)

    seat_responses = [SeatResponse.model_validate(s) for s in seats]

    return BookingDetailResponse(
        booking_id=booking.booking_id,
        event_id=booking.event_id,
        user_id=booking.user_id,
        total_amount=booking.total_amount,
        status=BookingStatus(booking.status.value),
        payment_status=PaymentStatus(booking.payment_status.value),
        booking_reference=booking.booking_reference,
        created_at=booking.created_at,
        confirmed_at=booking.confirmed_at,
        seats=seat_responses,
        event_name=event.event_name if event else None,
        venue_name=event.venue_name if event else None,
        event_date=event.event_date if event else None,
    )


@router.get(
    "/reference/{reference}",
    response_model=BookingResponse,
    summary="Get booking by reference",
)
async def get_booking_by_reference(
    reference: str,
    current_user: CurrentUser,
    booking_service: BookingServiceDep,
) -> BookingResponse:
    """Get booking by booking reference."""
    booking = await booking_service.get_booking_by_reference(reference)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's booking",
        )

    return BookingResponse(
        booking_id=booking.booking_id,
        event_id=booking.event_id,
        user_id=booking.user_id,
        total_amount=booking.total_amount,
        status=BookingStatus(booking.status.value),
        payment_status=PaymentStatus(booking.payment_status.value),
        booking_reference=booking.booking_reference,
        created_at=booking.created_at,
        confirmed_at=booking.confirmed_at,
        seats=[],
    )


@router.post(
    "/{booking_id}/confirm-payment",
    response_model=BookingResponse,
    summary="Confirm payment",
)
async def confirm_payment(
    booking_id: int,
    payment_data: PaymentConfirmRequest,
    current_user: CurrentUser,
    booking_service: BookingServiceDep,
) -> BookingResponse:
    """
    Confirm payment for a booking.
    
    In a real system, this would be called after payment gateway callback.
    """
    # Verify booking belongs to user
    booking = await booking_service.get_booking(booking_id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot confirm payment for another user's booking",
        )

    try:
        booking = await booking_service.confirm_payment(
            booking_id=booking_id,
            payment_id=payment_data.payment_id,
        )
    except BookingError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return BookingResponse(
        booking_id=booking.booking_id,
        event_id=booking.event_id,
        user_id=booking.user_id,
        total_amount=booking.total_amount,
        status=BookingStatus(booking.status.value),
        payment_status=PaymentStatus(booking.payment_status.value),
        booking_reference=booking.booking_reference,
        created_at=booking.created_at,
        confirmed_at=booking.confirmed_at,
        seats=[],
    )


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    summary="Cancel booking",
)
async def cancel_booking(
    booking_id: int,
    current_user: CurrentUser,
    booking_service: BookingServiceDep,
    cancel_data: BookingCancelRequest | None = None,
) -> BookingResponse:
    """Cancel a booking and release seats."""
    try:
        booking = await booking_service.cancel_booking(
            booking_id=booking_id,
            user_id=current_user,
        )
    except BookingError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return BookingResponse(
        booking_id=booking.booking_id,
        event_id=booking.event_id,
        user_id=booking.user_id,
        total_amount=booking.total_amount,
        status=BookingStatus(booking.status.value),
        payment_status=PaymentStatus(booking.payment_status.value),
        booking_reference=booking.booking_reference,
        created_at=booking.created_at,
        confirmed_at=booking.confirmed_at,
        seats=[],
    )

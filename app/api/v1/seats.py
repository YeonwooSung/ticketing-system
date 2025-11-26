"""Seats API endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import SeatServiceDep
from app.schemas.seat import SeatResponse

router = APIRouter()


@router.get(
    "/{seat_id}",
    response_model=SeatResponse,
    summary="Get seat details",
)
async def get_seat(
    seat_id: int,
    seat_service: SeatServiceDep,
) -> SeatResponse:
    """Get seat details by ID."""
    seat = await seat_service.get_seat(seat_id)
    if not seat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seat not found",
        )
    return SeatResponse.model_validate(seat)


@router.get(
    "",
    response_model=list[SeatResponse],
    summary="Get multiple seats",
)
async def get_seats(
    seat_ids: str,  # Comma-separated list
    seat_service: SeatServiceDep,
) -> list[SeatResponse]:
    """Get multiple seats by IDs."""
    try:
        ids = [int(id.strip()) for id in seat_ids.split(",")]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid seat IDs format",
        )

    seats = await seat_service.get_seats(ids)
    return [SeatResponse.model_validate(s) for s in seats]


@router.post(
    "/check-availability",
    response_model=dict,
    summary="Check seat availability",
)
async def check_availability(
    seat_ids: list[int],
    seat_service: SeatServiceDep,
) -> dict:
    """Check if seats are available."""
    available, seats = await seat_service.check_seats_available(seat_ids)

    seat_status = {}
    for seat in seats:
        seat_status[seat.seat_id] = {
            "seat_number": seat.seat_number,
            "status": seat.status.value,
            "is_available": seat.status.value == "AVAILABLE",
        }

    # Check for missing seats
    found_ids = {s.seat_id for s in seats}
    for seat_id in seat_ids:
        if seat_id not in found_ids:
            seat_status[seat_id] = {
                "seat_number": None,
                "status": "NOT_FOUND",
                "is_available": False,
            }

    return {
        "all_available": available,
        "seats": seat_status,
    }

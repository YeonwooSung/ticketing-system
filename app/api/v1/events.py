"""Events API endpoints."""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.v1.dependencies import DBSession, EventServiceDep, SeatServiceDep
from app.schemas.common import PaginatedResponse
from app.schemas.event import (
    EventCreate,
    EventDetailResponse,
    EventResponse,
    EventStatus,
    EventUpdate,
)
from app.schemas.seat import SeatAvailabilityResponse, SeatBulkCreate, SeatCreate, SeatResponse
from app.services.event_service import EventService
from app.services.seat_service import SeatService

router = APIRouter()


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new event",
)
async def create_event(
    event_data: EventCreate,
    event_service: EventServiceDep,
) -> EventResponse:
    """Create a new event."""
    event = await event_service.create_event(event_data)
    return EventResponse.model_validate(event)


@router.get(
    "",
    response_model=PaginatedResponse[EventResponse],
    summary="List events",
)
async def list_events(
    event_service: EventServiceDep,
    status_filter: EventStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[EventResponse]:
    """List events with optional filtering."""
    events, total = await event_service.get_events(
        status=status_filter,
        page=page,
        page_size=page_size,
    )

    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponse(
        items=[EventResponse.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{event_id}",
    response_model=EventDetailResponse,
    summary="Get event details",
)
async def get_event(
    event_id: int,
    event_service: EventServiceDep,
) -> EventDetailResponse:
    """Get event details with seat statistics."""
    result = await event_service.get_event_with_seat_counts(event_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    event = result["event"]
    return EventDetailResponse(
        event_id=event.event_id,
        event_name=event.event_name,
        event_date=event.event_date,
        venue_name=event.venue_name,
        total_seats=event.total_seats,
        available_seats=event.available_seats,
        status=EventStatus(event.status.value),
        sale_start_time=event.sale_start_time,
        created_at=event.created_at,
        available_seat_count=result["available_seat_count"],
        reserved_seat_count=result["reserved_seat_count"],
        booked_seat_count=result["booked_seat_count"],
    )


@router.patch(
    "/{event_id}",
    response_model=EventResponse,
    summary="Update event",
)
async def update_event(
    event_id: int,
    event_data: EventUpdate,
    event_service: EventServiceDep,
) -> EventResponse:
    """Update an event."""
    event = await event_service.update_event(event_id, event_data)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return EventResponse.model_validate(event)


@router.post(
    "/{event_id}/start-sale",
    response_model=EventResponse,
    summary="Start ticket sales",
)
async def start_sale(
    event_id: int,
    event_service: EventServiceDep,
) -> EventResponse:
    """Start ticket sales for an event."""
    from app.models.event import EventStatus as ModelEventStatus

    event = await event_service.update_event_status(
        event_id, ModelEventStatus.ON_SALE
    )
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return EventResponse.model_validate(event)


@router.post(
    "/{event_id}/seats",
    response_model=list[SeatResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Add seats to event",
)
async def add_seats(
    event_id: int,
    seats_data: list[SeatCreate],
    event_service: EventServiceDep,
    seat_service: SeatServiceDep,
) -> list[SeatResponse]:
    """Add seats to an event."""
    # Verify event exists
    event = await event_service.get_event(event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    seats = await seat_service.create_seats_bulk(event_id, seats_data)
    return [SeatResponse.model_validate(s) for s in seats]


@router.get(
    "/{event_id}/seats",
    response_model=list[SeatResponse],
    summary="Get seats for event",
)
async def get_event_seats(
    event_id: int,
    seat_service: SeatServiceDep,
    section: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
) -> list[SeatResponse]:
    """Get all seats for an event."""
    from app.models.seat import SeatStatus as ModelSeatStatus

    seat_status = None
    if status_filter:
        try:
            seat_status = ModelSeatStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    seats = await seat_service.get_seats_by_event(
        event_id,
        status=seat_status,
        section=section,
    )
    return [SeatResponse.model_validate(s) for s in seats]


@router.get(
    "/{event_id}/seats/available",
    response_model=list[SeatAvailabilityResponse],
    summary="Get available seats",
)
async def get_available_seats(
    event_id: int,
    seat_service: SeatServiceDep,
) -> list[SeatAvailabilityResponse]:
    """Get available seats for an event."""
    seats = await seat_service.get_available_seats(event_id)
    return [
        SeatAvailabilityResponse(
            seat_id=s.seat_id,
            seat_number=s.seat_number,
            section=s.section,
            seat_type=s.seat_type.value,
            price=s.price,
            is_available=True,
            status=s.status.value,
        )
        for s in seats
    ]

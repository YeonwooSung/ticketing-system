"""Event service."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event, EventStatus
from app.models.seat import Seat, SeatStatus
from app.schemas.event import EventCreate, EventUpdate


class EventService:
    """Service for event operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_event(self, event_data: EventCreate) -> Event:
        """Create a new event."""
        event = Event(
            event_name=event_data.event_name,
            event_date=event_data.event_date,
            venue_name=event_data.venue_name,
            total_seats=event_data.total_seats,
            available_seats=event_data.total_seats,
            status=EventStatus.UPCOMING,
            sale_start_time=event_data.sale_start_time,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def get_event(self, event_id: int) -> Event | None:
        """Get event by ID."""
        result = await self.db.execute(
            select(Event).where(Event.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def get_events(
        self,
        status: EventStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Event], int]:
        """Get events with optional filtering."""
        query = select(Event)

        if status:
            query = query.where(Event.status == status)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # Get paginated results
        query = query.order_by(Event.event_date.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        events = list(result.scalars().all())

        return events, total

    async def get_event_with_seat_counts(self, event_id: int) -> dict | None:
        """Get event with seat count statistics."""
        event = await self.get_event(event_id)
        if not event:
            return None

        # Get seat counts by status
        count_query = select(
            Seat.status,
            func.count(Seat.seat_id).label("count")
        ).where(
            Seat.event_id == event_id
        ).group_by(Seat.status)

        result = await self.db.execute(count_query)
        counts = {row.status: row.count for row in result}

        return {
            "event": event,
            "available_seat_count": counts.get(SeatStatus.AVAILABLE, 0),
            "reserved_seat_count": counts.get(SeatStatus.RESERVED, 0),
            "booked_seat_count": counts.get(SeatStatus.BOOKED, 0),
        }

    async def update_event(
        self,
        event_id: int,
        event_data: EventUpdate,
    ) -> Event | None:
        """Update an event."""
        event = await self.get_event(event_id)
        if not event:
            return None

        update_data = event_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(event, field, value)

        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def update_event_status(
        self,
        event_id: int,
        status: EventStatus,
    ) -> Event | None:
        """Update event status."""
        event = await self.get_event(event_id)
        if not event:
            return None

        event.status = status
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def update_available_seats(
        self,
        event_id: int,
        delta: int,
    ) -> bool:
        """Update available seats count."""
        event = await self.get_event(event_id)
        if not event:
            return False

        new_count = event.available_seats + delta
        if new_count < 0 or new_count > event.total_seats:
            return False

        event.available_seats = new_count

        # Auto-update status
        if new_count == 0:
            event.status = EventStatus.SOLD_OUT
        elif event.status == EventStatus.SOLD_OUT and new_count > 0:
            event.status = EventStatus.ON_SALE

        await self.db.commit()
        return True

    async def check_sale_started(self, event_id: int) -> bool:
        """Check if ticket sales have started for an event."""
        event = await self.get_event(event_id)
        if not event:
            return False

        if event.status == EventStatus.CANCELLED:
            return False

        if event.status not in [EventStatus.ON_SALE, EventStatus.UPCOMING]:
            return event.status == EventStatus.SOLD_OUT

        if event.sale_start_time and event.sale_start_time > datetime.now():
            return False

        return True

"""Seat service."""

from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.seat import Seat, SeatStatus, SeatType
from app.schemas.seat import SeatCreate


class SeatService:
    """Service for seat operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_seat(self, event_id: int, seat_data: SeatCreate) -> Seat:
        """Create a new seat."""
        seat = Seat(
            event_id=event_id,
            seat_number=seat_data.seat_number,
            section=seat_data.section,
            row_number=seat_data.row_number,
            seat_type=SeatType(seat_data.seat_type.value),
            price=seat_data.price,
            status=SeatStatus.AVAILABLE,
        )
        self.db.add(seat)
        await self.db.commit()
        await self.db.refresh(seat)
        return seat

    async def create_seats_bulk(
        self,
        event_id: int,
        seats_data: list[SeatCreate],
    ) -> list[Seat]:
        """Create multiple seats at once."""
        seats = []
        for seat_data in seats_data:
            seat = Seat(
                event_id=event_id,
                seat_number=seat_data.seat_number,
                section=seat_data.section,
                row_number=seat_data.row_number,
                seat_type=SeatType(seat_data.seat_type.value),
                price=seat_data.price,
                status=SeatStatus.AVAILABLE,
            )
            seats.append(seat)
            self.db.add(seat)

        await self.db.commit()

        # Refresh all seats
        for seat in seats:
            await self.db.refresh(seat)

        return seats

    async def get_seat(self, seat_id: int) -> Seat | None:
        """Get seat by ID."""
        result = await self.db.execute(
            select(Seat).where(Seat.seat_id == seat_id)
        )
        return result.scalar_one_or_none()

    async def get_seats(self, seat_ids: list[int]) -> list[Seat]:
        """Get multiple seats by IDs."""
        result = await self.db.execute(
            select(Seat).where(Seat.seat_id.in_(seat_ids))
        )
        return list(result.scalars().all())

    async def get_seats_by_event(
        self,
        event_id: int,
        status: SeatStatus | None = None,
        section: str | None = None,
        seat_type: SeatType | None = None,
    ) -> list[Seat]:
        """Get seats for an event with optional filtering."""
        query = select(Seat).where(Seat.event_id == event_id)

        if status:
            query = query.where(Seat.status == status)
        if section:
            query = query.where(Seat.section == section)
        if seat_type:
            query = query.where(Seat.seat_type == seat_type)

        query = query.order_by(Seat.section, Seat.row_number, Seat.seat_number)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_available_seats(self, event_id: int) -> list[Seat]:
        """Get all available seats for an event."""
        return await self.get_seats_by_event(event_id, status=SeatStatus.AVAILABLE)

    async def check_seats_available(self, seat_ids: list[int]) -> tuple[bool, list[Seat]]:
        """
        Check if all seats are available.

        Returns:
            Tuple of (all_available, list of seats)
        """
        seats = await self.get_seats(seat_ids)

        if len(seats) != len(seat_ids):
            return False, seats

        all_available = all(seat.status == SeatStatus.AVAILABLE for seat in seats)
        return all_available, seats

    async def update_seat_status(
        self,
        seat_id: int,
        status: SeatStatus,
        reserved_by: str | None = None,
        reserved_until: datetime | None = None,
        booking_id: int | None = None,
        expected_version: int | None = None,
    ) -> Seat | None:
        """
        Update seat status with optimistic locking.

        Args:
            seat_id: Seat ID
            status: New status
            reserved_by: User ID for reservation
            reserved_until: Reservation expiration
            booking_id: Booking ID if booked
            expected_version: Expected version for optimistic locking

        Returns:
            Updated seat or None if update failed
        """
        seat = await self.get_seat(seat_id)
        if not seat:
            return None

        # Optimistic locking check
        if expected_version is not None and seat.version != expected_version:
            return None

        seat.status = status
        seat.reserved_by = reserved_by
        seat.reserved_until = reserved_until
        seat.booking_id = booking_id
        seat.version += 1

        await self.db.commit()
        await self.db.refresh(seat)
        return seat

    async def release_expired_reservations(self) -> int:
        """
        Release seats with expired reservations.

        Returns:
            Number of seats released
        """
        now = datetime.now()

        query = select(Seat).where(
            and_(
                Seat.status == SeatStatus.RESERVED,
                Seat.reserved_until < now,
            )
        )

        result = await self.db.execute(query)
        expired_seats = list(result.scalars().all())

        count = 0
        for seat in expired_seats:
            seat.status = SeatStatus.AVAILABLE
            seat.reserved_by = None
            seat.reserved_until = None
            seat.version += 1
            count += 1

        if count > 0:
            await self.db.commit()

        return count

    async def get_seat_for_update(self, seat_id: int) -> Seat | None:
        """
        Get seat with row-level lock for update.
        This uses SELECT ... FOR UPDATE pattern.
        """
        result = await self.db.execute(
            select(Seat)
            .where(Seat.seat_id == seat_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_seats_for_update(self, seat_ids: list[int]) -> list[Seat]:
        """
        Get multiple seats with row-level locks.
        Orders by seat_id to prevent deadlocks.
        """
        result = await self.db.execute(
            select(Seat)
            .where(Seat.seat_id.in_(seat_ids))
            .order_by(Seat.seat_id)
            .with_for_update()
        )
        return list(result.scalars().all())

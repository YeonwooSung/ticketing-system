"""Reservation service with distributed locking."""

from datetime import datetime, timedelta
from decimal import Decimal

import redis.asyncio as redis
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.distributed_lock import DistributedLockError, multi_lock
from app.models.reservation import Reservation, ReservationStatus
from app.models.seat import Seat, SeatStatus

settings = get_settings()


class ReservationError(Exception):
    """Reservation operation error."""

    pass


class ReservationService:
    """Service for reservation operations with distributed locking."""

    def __init__(self, db: AsyncSession, redis_client: redis.Redis):
        self.db = db
        self.redis = redis_client

    async def reserve_seats(
        self,
        event_id: int,
        seat_ids: list[int],
        user_id: str,
        session_id: str | None = None,
    ) -> tuple[list[Reservation], Decimal]:
        """
        Reserve multiple seats atomically using distributed locks.

        Args:
            event_id: Event ID
            seat_ids: List of seat IDs to reserve
            user_id: User ID making the reservation
            session_id: Optional session ID

        Returns:
            Tuple of (list of reservations, total amount)

        Raises:
            ReservationError: If reservation fails
        """
        if len(seat_ids) > settings.MAX_SEATS_PER_BOOKING:
            raise ReservationError(
                f"Cannot reserve more than {settings.MAX_SEATS_PER_BOOKING} seats"
            )

        # Create lock keys for all seats
        lock_keys = [f"seat:{seat_id}" for seat_id in seat_ids]

        try:
            async with multi_lock(self.redis, lock_keys, blocking=True):
                # All locks acquired, now perform the reservation
                return await self._do_reserve_seats(
                    event_id, seat_ids, user_id, session_id
                )
        except DistributedLockError:
            raise ReservationError(
                "Unable to acquire locks for seats. Please try again."
            )

    async def _do_reserve_seats(
        self,
        event_id: int,
        seat_ids: list[int],
        user_id: str,
        session_id: str | None,
    ) -> tuple[list[Reservation], Decimal]:
        """
        Internal method to perform seat reservation.
        Should be called within a distributed lock context.
        """
        # Get seats with database-level lock
        result = await self.db.execute(
            select(Seat)
            .where(Seat.seat_id.in_(seat_ids))
            .order_by(Seat.seat_id)
            .with_for_update()
        )
        seats = list(result.scalars().all())

        # Validate all seats exist and belong to the event
        if len(seats) != len(seat_ids):
            raise ReservationError("One or more seats not found")

        for seat in seats:
            if seat.event_id != event_id:
                raise ReservationError(
                    f"Seat {seat.seat_id} does not belong to event {event_id}"
                )

        # Check all seats are available
        unavailable = [s for s in seats if s.status != SeatStatus.AVAILABLE]
        if unavailable:
            seat_numbers = [s.seat_number for s in unavailable]
            raise ReservationError(
                f"Seats not available: {', '.join(seat_numbers)}"
            )

        # Calculate expiration time
        expires_at = datetime.now() + timedelta(
            seconds=settings.RESERVATION_TIMEOUT_SECONDS
        )

        # Create reservations and update seats
        reservations = []
        total_amount = Decimal("0")

        for seat in seats:
            # Update seat status
            seat.status = SeatStatus.RESERVED
            seat.reserved_by = user_id
            seat.reserved_until = expires_at
            seat.version += 1

            # Create reservation record
            reservation = Reservation(
                seat_id=seat.seat_id,
                event_id=event_id,
                user_id=user_id,
                session_id=session_id,
                expires_at=expires_at,
                status=ReservationStatus.ACTIVE,
            )
            self.db.add(reservation)
            reservations.append(reservation)
            total_amount += seat.price

        await self.db.commit()

        # Refresh reservations to get IDs
        for reservation in reservations:
            await self.db.refresh(reservation)

        return reservations, total_amount

    async def get_reservation(self, reservation_id: int) -> Reservation | None:
        """Get reservation by ID."""
        result = await self.db.execute(
            select(Reservation).where(Reservation.reservation_id == reservation_id)
        )
        return result.scalar_one_or_none()

    async def get_user_reservations(
        self,
        user_id: str,
        event_id: int | None = None,
        status: ReservationStatus | None = None,
    ) -> list[Reservation]:
        """Get reservations for a user."""
        query = select(Reservation).where(Reservation.user_id == user_id)

        if event_id:
            query = query.where(Reservation.event_id == event_id)
        if status:
            query = query.where(Reservation.status == status)

        query = query.order_by(Reservation.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_active_reservations_by_seat(
        self,
        seat_ids: list[int],
    ) -> list[Reservation]:
        """Get active reservations for given seats."""
        result = await self.db.execute(
            select(Reservation).where(
                and_(
                    Reservation.seat_id.in_(seat_ids),
                    Reservation.status == ReservationStatus.ACTIVE,
                )
            )
        )
        return list(result.scalars().all())

    async def cancel_reservation(
        self,
        reservation_id: int,
        user_id: str,
    ) -> bool:
        """
        Cancel a reservation.

        Returns:
            True if cancelled successfully
        """
        reservation = await self.get_reservation(reservation_id)
        if not reservation:
            return False

        if reservation.user_id != user_id:
            raise ReservationError("Cannot cancel another user's reservation")

        if reservation.status != ReservationStatus.ACTIVE:
            raise ReservationError("Reservation is not active")

        # Lock the seat
        lock_key = f"seat:{reservation.seat_id}"

        try:
            async with multi_lock(self.redis, [lock_key], blocking=True):
                # Get seat with lock
                result = await self.db.execute(
                    select(Seat)
                    .where(Seat.seat_id == reservation.seat_id)
                    .with_for_update()
                )
                seat = result.scalar_one_or_none()

                if seat and seat.status == SeatStatus.RESERVED:
                    seat.status = SeatStatus.AVAILABLE
                    seat.reserved_by = None
                    seat.reserved_until = None
                    seat.version += 1

                reservation.status = ReservationStatus.CANCELLED
                await self.db.commit()

                return True
        except DistributedLockError:
            raise ReservationError("Failed to cancel reservation. Please try again.")

    async def cancel_reservations_batch(
        self,
        reservation_ids: list[int],
        user_id: str,
    ) -> int:
        """
        Cancel multiple reservations.

        Returns:
            Number of reservations cancelled
        """
        cancelled = 0
        for res_id in reservation_ids:
            try:
                if await self.cancel_reservation(res_id, user_id):
                    cancelled += 1
            except ReservationError:
                continue
        return cancelled

    async def extend_reservation(
        self,
        reservation_id: int,
        user_id: str,
        additional_minutes: int = 5,
    ) -> Reservation | None:
        """Extend reservation expiration time."""
        reservation = await self.get_reservation(reservation_id)
        if not reservation:
            return None

        if reservation.user_id != user_id:
            raise ReservationError("Cannot extend another user's reservation")

        if reservation.status != ReservationStatus.ACTIVE:
            raise ReservationError("Reservation is not active")

        # Lock the seat
        lock_key = f"seat:{reservation.seat_id}"

        try:
            async with multi_lock(self.redis, [lock_key], blocking=True):
                new_expires = datetime.now() + timedelta(minutes=additional_minutes)

                # Update seat
                result = await self.db.execute(
                    select(Seat)
                    .where(Seat.seat_id == reservation.seat_id)
                    .with_for_update()
                )
                seat = result.scalar_one_or_none()

                if seat:
                    seat.reserved_until = new_expires

                reservation.expires_at = new_expires
                await self.db.commit()
                await self.db.refresh(reservation)

                return reservation
        except DistributedLockError:
            raise ReservationError("Failed to extend reservation. Please try again.")

    async def confirm_reservations(
        self,
        seat_ids: list[int],
        user_id: str,
    ) -> bool:
        """
        Mark reservations as confirmed (called when booking is created).

        Returns:
            True if all reservations were confirmed
        """
        result = await self.db.execute(
            update(Reservation)
            .where(
                and_(
                    Reservation.seat_id.in_(seat_ids),
                    Reservation.user_id == user_id,
                    Reservation.status == ReservationStatus.ACTIVE,
                )
            )
            .values(status=ReservationStatus.CONFIRMED)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def expire_old_reservations(self) -> int:
        """
        Expire old reservations and release seats.

        Returns:
            Number of reservations expired
        """
        now = datetime.now()

        # Find expired reservations
        result = await self.db.execute(
            select(Reservation).where(
                and_(
                    Reservation.status == ReservationStatus.ACTIVE,
                    Reservation.expires_at < now,
                )
            )
        )
        expired_reservations = list(result.scalars().all())

        count = 0
        for reservation in expired_reservations:
            # Update reservation status
            reservation.status = ReservationStatus.EXPIRED

            # Release seat
            seat_result = await self.db.execute(
                select(Seat).where(Seat.seat_id == reservation.seat_id)
            )
            seat = seat_result.scalar_one_or_none()

            if seat and seat.status == SeatStatus.RESERVED:
                seat.status = SeatStatus.AVAILABLE
                seat.reserved_by = None
                seat.reserved_until = None
                seat.version += 1

            count += 1

        if count > 0:
            await self.db.commit()

        return count

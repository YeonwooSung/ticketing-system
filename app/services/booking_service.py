"""Booking service with distributed locking."""

from datetime import datetime

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.distributed_lock import DistributedLockError, multi_lock
from app.models.booking import Booking, BookingSeat, BookingStatus, PaymentStatus
from app.models.seat import Seat, SeatStatus
from app.services.reservation_service import ReservationService


class BookingError(Exception):
    """Booking operation error."""

    pass


class BookingService:
    """Service for booking operations with distributed locking."""

    def __init__(self, db: AsyncSession, redis_client: redis.Redis):
        self.db = db
        self.redis = redis_client
        self.reservation_service = ReservationService(db, redis_client)

    def _generate_booking_reference(self) -> str:
        """Generate unique booking reference using ULID."""
        return f"BK-{str(ULID())}"

    async def create_booking(
        self,
        event_id: int,
        user_id: str,
        seat_ids: list[int],
    ) -> Booking:
        """
        Create a booking from reserved seats.

        The seats must already be reserved by the user.

        Args:
            event_id: Event ID
            user_id: User ID
            seat_ids: List of seat IDs to book

        Returns:
            Created booking

        Raises:
            BookingError: If booking fails
        """
        if not seat_ids:
            raise BookingError("No seats specified")

        # Create lock keys for all seats
        lock_keys = [f"seat:{seat_id}" for seat_id in seat_ids]

        try:
            async with multi_lock(self.redis, lock_keys, blocking=True):
                return await self._do_create_booking(event_id, user_id, seat_ids)
        except DistributedLockError:
            raise BookingError(
                "Unable to acquire locks for seats. Please try again."
            )

    async def _do_create_booking(
        self,
        event_id: int,
        user_id: str,
        seat_ids: list[int],
    ) -> Booking:
        """
        Internal method to create booking.
        Should be called within a distributed lock context.
        """
        # Get seats with database lock
        result = await self.db.execute(
            select(Seat)
            .where(Seat.seat_id.in_(seat_ids))
            .order_by(Seat.seat_id)
            .with_for_update()
        )
        seats = list(result.scalars().all())

        # Validate seats
        if len(seats) != len(seat_ids):
            raise BookingError("One or more seats not found")

        # Check all seats are reserved by this user
        for seat in seats:
            if seat.event_id != event_id:
                raise BookingError(
                    f"Seat {seat.seat_id} does not belong to event {event_id}"
                )
            if seat.status != SeatStatus.RESERVED:
                raise BookingError(
                    f"Seat {seat.seat_number} is not reserved"
                )
            if seat.reserved_by != user_id:
                raise BookingError(
                    f"Seat {seat.seat_number} is not reserved by you"
                )

        # Calculate total amount
        total_amount = sum(seat.price for seat in seats)

        # Create booking
        booking = Booking(
            event_id=event_id,
            user_id=user_id,
            total_amount=total_amount,
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
            booking_reference=self._generate_booking_reference(),
        )
        self.db.add(booking)
        await self.db.flush()  # Get booking_id

        # Create booking seats and update seat status
        for seat in seats:
            booking_seat = BookingSeat(
                booking_id=booking.booking_id,
                seat_id=seat.seat_id,
                price=seat.price,
            )
            self.db.add(booking_seat)

            # Update seat to booked
            seat.status = SeatStatus.BOOKED
            seat.booking_id = booking.booking_id
            seat.reserved_by = None
            seat.reserved_until = None
            seat.version += 1

        # Confirm reservations
        await self.reservation_service.confirm_reservations(seat_ids, user_id)

        await self.db.commit()
        await self.db.refresh(booking)

        return booking

    async def get_booking(self, booking_id: int) -> Booking | None:
        """Get booking by ID."""
        result = await self.db.execute(
            select(Booking).where(Booking.booking_id == booking_id)
        )
        return result.scalar_one_or_none()

    async def get_booking_by_reference(self, reference: str) -> Booking | None:
        """Get booking by reference."""
        result = await self.db.execute(
            select(Booking).where(Booking.booking_reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_user_bookings(
        self,
        user_id: str,
        status: BookingStatus | None = None,
    ) -> list[Booking]:
        """Get bookings for a user."""
        query = select(Booking).where(Booking.user_id == user_id)

        if status:
            query = query.where(Booking.status == status)

        query = query.order_by(Booking.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_booking_seats(self, booking_id: int) -> list[Seat]:
        """Get seats for a booking."""
        result = await self.db.execute(
            select(Seat).where(Seat.booking_id == booking_id)
        )
        return list(result.scalars().all())

    async def confirm_payment(
        self,
        booking_id: int,
        payment_id: str,
    ) -> Booking:
        """
        Confirm payment for a booking.

        Args:
            booking_id: Booking ID
            payment_id: External payment ID

        Returns:
            Updated booking

        Raises:
            BookingError: If confirmation fails
        """
        booking = await self.get_booking(booking_id)
        if not booking:
            raise BookingError("Booking not found")

        if booking.status != BookingStatus.PENDING:
            raise BookingError("Booking is not pending")

        booking.payment_id = payment_id
        booking.payment_status = PaymentStatus.SUCCESS
        booking.status = BookingStatus.CONFIRMED
        booking.confirmed_at = datetime.now()

        await self.db.commit()
        await self.db.refresh(booking)

        return booking

    async def fail_payment(
        self,
        booking_id: int,
        payment_id: str | None = None,
    ) -> Booking:
        """
        Mark payment as failed and release seats.

        Args:
            booking_id: Booking ID
            payment_id: External payment ID

        Returns:
            Updated booking
        """
        booking = await self.get_booking(booking_id)
        if not booking:
            raise BookingError("Booking not found")

        if booking.status != BookingStatus.PENDING:
            raise BookingError("Booking is not pending")

        # Get seats for this booking
        seats = await self.get_booking_seats(booking_id)
        seat_ids = [seat.seat_id for seat in seats]

        # Lock seats
        lock_keys = [f"seat:{seat_id}" for seat_id in seat_ids]

        try:
            async with multi_lock(self.redis, lock_keys, blocking=True):
                # Release seats
                for seat in seats:
                    result = await self.db.execute(
                        select(Seat)
                        .where(Seat.seat_id == seat.seat_id)
                        .with_for_update()
                    )
                    db_seat = result.scalar_one_or_none()
                    if db_seat:
                        db_seat.status = SeatStatus.AVAILABLE
                        db_seat.booking_id = None
                        db_seat.version += 1

                # Update booking
                booking.payment_id = payment_id
                booking.payment_status = PaymentStatus.FAILED
                booking.status = BookingStatus.FAILED

                await self.db.commit()
                await self.db.refresh(booking)

                return booking
        except DistributedLockError:
            raise BookingError("Failed to release seats. Please contact support.")

    async def cancel_booking(
        self,
        booking_id: int,
        user_id: str,
    ) -> Booking:
        """
        Cancel a booking and release seats.

        Args:
            booking_id: Booking ID
            user_id: User ID (for authorization)

        Returns:
            Cancelled booking
        """
        booking = await self.get_booking(booking_id)
        if not booking:
            raise BookingError("Booking not found")

        if booking.user_id != user_id:
            raise BookingError("Cannot cancel another user's booking")

        if booking.status not in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
            raise BookingError("Booking cannot be cancelled")

        # Get seats for this booking
        seats = await self.get_booking_seats(booking_id)
        seat_ids = [seat.seat_id for seat in seats]

        # Lock seats
        lock_keys = [f"seat:{seat_id}" for seat_id in seat_ids]

        try:
            async with multi_lock(self.redis, lock_keys, blocking=True):
                # Release seats
                for seat in seats:
                    result = await self.db.execute(
                        select(Seat)
                        .where(Seat.seat_id == seat.seat_id)
                        .with_for_update()
                    )
                    db_seat = result.scalar_one_or_none()
                    if db_seat:
                        db_seat.status = SeatStatus.AVAILABLE
                        db_seat.booking_id = None
                        db_seat.version += 1

                # Update booking
                booking.status = BookingStatus.CANCELLED

                await self.db.commit()
                await self.db.refresh(booking)

                return booking
        except DistributedLockError:
            raise BookingError("Failed to cancel booking. Please try again.")

    async def get_booking_with_seats(self, booking_id: int) -> dict | None:
        """Get booking with seat details."""
        booking = await self.get_booking(booking_id)
        if not booking:
            return None

        seats = await self.get_booking_seats(booking_id)

        return {
            "booking": booking,
            "seats": seats,
        }

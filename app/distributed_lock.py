"""Distributed lock implementation using Redis."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()


class DistributedLockError(Exception):
    """Exception raised when lock acquisition fails."""

    pass


class DistributedLock:
    """
    Redis-based distributed lock implementation.
    
    Uses SET NX EX pattern for atomic lock acquisition with expiration.
    Implements proper lock release with Lua script to avoid race conditions.
    """

    # Lua script for safe lock release (only release if we own the lock)
    RELEASE_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    # Lua script for lock extension
    EXTEND_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("pexpire", KEYS[1], ARGV[2])
    else
        return 0
    end
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        key: str,
        timeout_seconds: int | None = None,
        retry_delay_ms: int | None = None,
        max_retries: int | None = None,
    ):
        """
        Initialize distributed lock.

        Args:
            redis_client: Redis client instance
            key: Lock key name
            timeout_seconds: Lock expiration time in seconds
            retry_delay_ms: Delay between retry attempts in milliseconds
            max_retries: Maximum number of retry attempts
        """
        self.redis = redis_client
        self.key = f"lock:{key}"
        self.timeout_seconds = timeout_seconds or settings.LOCK_TIMEOUT_SECONDS
        self.retry_delay_ms = retry_delay_ms or settings.LOCK_RETRY_DELAY_MS
        self.max_retries = max_retries or settings.LOCK_MAX_RETRIES
        self.token: str | None = None
        self._release_script = self.redis.register_script(self.RELEASE_SCRIPT)
        self._extend_script = self.redis.register_script(self.EXTEND_SCRIPT)

    async def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire the lock.

        Args:
            blocking: If True, retry until lock is acquired or max retries reached.
                     If False, try once and return immediately.

        Returns:
            True if lock was acquired, False otherwise.
        """
        self.token = str(uuid.uuid4())
        retries = 0

        while True:
            # Try to acquire lock with SET NX EX
            acquired = await self.redis.set(
                self.key,
                self.token,
                nx=True,
                ex=self.timeout_seconds,
            )

            if acquired:
                return True

            if not blocking or retries >= self.max_retries:
                self.token = None
                return False

            retries += 1
            await asyncio.sleep(self.retry_delay_ms / 1000)

    async def release(self) -> bool:
        """
        Release the lock.

        Returns:
            True if lock was released, False if we didn't own the lock.
        """
        if self.token is None:
            return False

        result = await self._release_script(keys=[self.key], args=[self.token])
        self.token = None
        return bool(result)

    async def extend(self, additional_seconds: int | None = None) -> bool:
        """
        Extend the lock expiration time.

        Args:
            additional_seconds: Additional time in seconds. Defaults to timeout_seconds.

        Returns:
            True if lock was extended, False if we didn't own the lock.
        """
        if self.token is None:
            return False

        timeout = additional_seconds or self.timeout_seconds
        result = await self._extend_script(
            keys=[self.key],
            args=[self.token, timeout * 1000],
        )
        return bool(result)

    async def is_locked(self) -> bool:
        """Check if lock is currently held by anyone."""
        return await self.redis.exists(self.key) == 1

    async def owned(self) -> bool:
        """Check if we currently own the lock."""
        if self.token is None:
            return False
        current = await self.redis.get(self.key)
        return current == self.token


@asynccontextmanager
async def distributed_lock(
    redis_client: redis.Redis,
    key: str,
    timeout_seconds: int | None = None,
    blocking: bool = True,
) -> AsyncGenerator[DistributedLock, None]:
    """
    Context manager for distributed lock.

    Usage:
        async with distributed_lock(redis, "seat:123") as lock:
            # Critical section
            ...

    Args:
        redis_client: Redis client instance
        key: Lock key name
        timeout_seconds: Lock expiration time in seconds
        blocking: If True, wait for lock acquisition

    Raises:
        DistributedLockError: If lock cannot be acquired
    """
    lock = DistributedLock(redis_client, key, timeout_seconds)
    acquired = await lock.acquire(blocking=blocking)

    if not acquired:
        raise DistributedLockError(f"Failed to acquire lock for key: {key}")

    try:
        yield lock
    finally:
        await lock.release()


class MultiLock:
    """
    Acquire multiple locks atomically.
    
    Uses sorted order to prevent deadlocks.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        keys: list[str],
        timeout_seconds: int | None = None,
    ):
        """
        Initialize multi-lock.

        Args:
            redis_client: Redis client instance
            keys: List of lock key names
            timeout_seconds: Lock expiration time in seconds
        """
        self.redis = redis_client
        self.timeout_seconds = timeout_seconds or settings.LOCK_TIMEOUT_SECONDS
        # Sort keys to prevent deadlocks
        self.sorted_keys = sorted(keys)
        self.locks: list[DistributedLock] = []

    async def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire all locks in sorted order.

        Returns:
            True if all locks were acquired, False otherwise.
        """
        for key in self.sorted_keys:
            lock = DistributedLock(self.redis, key, self.timeout_seconds)
            if await lock.acquire(blocking=blocking):
                self.locks.append(lock)
            else:
                # Failed to acquire one lock, release all acquired locks
                await self.release()
                return False
        return True

    async def release(self) -> None:
        """Release all locks in reverse order."""
        for lock in reversed(self.locks):
            await lock.release()
        self.locks.clear()


@asynccontextmanager
async def multi_lock(
    redis_client: redis.Redis,
    keys: list[str],
    timeout_seconds: int | None = None,
    blocking: bool = True,
) -> AsyncGenerator[MultiLock, None]:
    """
    Context manager for acquiring multiple locks.

    Usage:
        async with multi_lock(redis, ["seat:1", "seat:2", "seat:3"]) as lock:
            # Critical section with all seats locked
            ...

    Args:
        redis_client: Redis client instance
        keys: List of lock key names
        timeout_seconds: Lock expiration time in seconds
        blocking: If True, wait for lock acquisition

    Raises:
        DistributedLockError: If locks cannot be acquired
    """
    mlock = MultiLock(redis_client, keys, timeout_seconds)
    acquired = await mlock.acquire(blocking=blocking)

    if not acquired:
        raise DistributedLockError(f"Failed to acquire locks for keys: {keys}")

    try:
        yield mlock
    finally:
        await mlock.release()

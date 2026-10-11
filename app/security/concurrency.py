import asyncio
from dataclasses import dataclass
from typing import Self


@dataclass
class ConcurrencyLease:
    _limiter: "ConcurrencyLimiter"
    key_id: str
    _released: bool = False

    async def release(self) -> None:
        if self._released:
            return

        self._released = True
        cleanup = asyncio.create_task(self._limiter._release(self.key_id))

        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # Finish accounting even if the request task is cancelled during cleanup.
            await cleanup
            raise

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.release()


class ConcurrencyLimiter:
    """Non-waiting global/per-key concurrency guard with cancellation-safe leases."""

    def __init__(self, global_limit: int, per_key_limit: int) -> None:
        if global_limit < 1 or per_key_limit < 1 or per_key_limit > global_limit:
            raise ValueError("invalid concurrency limits")

        self.global_limit = global_limit
        self.per_key_limit = per_key_limit
        self._global_active = 0
        self._per_key_active: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def try_acquire(self, key_id: str) -> ConcurrencyLease | None:
        async with self._lock:
            active_for_key = self._per_key_active.get(key_id, 0)

            if (
                self._global_active >= self.global_limit
                or active_for_key >= self.per_key_limit
            ):
                return None

            self._global_active += 1
            self._per_key_active[key_id] = active_for_key + 1
            return ConcurrencyLease(self, key_id)

    async def _release(self, key_id: str) -> None:
        async with self._lock:
            active_for_key = self._per_key_active.get(key_id, 0)

            if active_for_key <= 0 or self._global_active <= 0:
                raise RuntimeError("concurrency lease accounting underflow")

            self._global_active -= 1

            if active_for_key == 1:
                del self._per_key_active[key_id]
            else:
                self._per_key_active[key_id] = active_for_key - 1

    async def snapshot(self) -> tuple[int, dict[str, int]]:
        async with self._lock:
            return self._global_active, dict(self._per_key_active)

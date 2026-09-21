"""Minimal scheduler port with overlap protection and graceful shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class IntervalScheduler:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[None]] = []
        self._callbacks: dict[str, Callable[[], Awaitable[None]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._stopping = False

    def add_interval(self, callback: Callable[[], Awaitable[None]], *, seconds: float, name: str) -> str:
        if seconds <= 0:
            raise ValueError("scheduler interval must be positive")
        if self._stopping:
            raise RuntimeError("scheduler is stopping")
        if name in self._callbacks:
            raise ValueError(f"scheduler job already exists: {name}")
        self._callbacks[name] = callback
        self._locks[name] = asyncio.Lock()

        async def runner() -> None:
            while not self._stopping:
                await asyncio.sleep(seconds)
                await self.trigger(name)

        self._tasks.append(asyncio.create_task(runner(), name=f"repo-health-scheduler:{name}"))
        return name

    async def trigger(self, name: str) -> bool:
        callback = self._callbacks.get(name)
        lock = self._locks.get(name)
        if callback is None or lock is None or self._stopping or lock.locked():
            return False
        async with lock:
            await callback()
        return True

    def status(self) -> dict[str, object]:
        return {
            "stopping": self._stopping,
            "jobs": tuple(
                {
                    "name": name,
                    "running": not task.done(),
                    "cancelled": task.cancelled(),
                }
                for name, task in zip(self._callbacks, self._tasks, strict=False)
            ),
        }

    async def shutdown(self) -> None:
        self._stopping = True
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._callbacks.clear()
        self._locks.clear()


__all__ = ["IntervalScheduler"]

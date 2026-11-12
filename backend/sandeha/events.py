"""Thread-safe event bus fanned out to WebSocket clients."""
from __future__ import annotations

import asyncio
import json
import time


class EventBus:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[asyncio.Queue] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)

    def _fanout(self, msg: str) -> None:
        for q in list(self.clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def publish(self, type_: str, payload) -> None:
        if self.loop is None or not self.clients:
            return
        msg = json.dumps({"type": type_, "ts": time.time(), "payload": payload}, default=str)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._fanout(msg)
        else:
            self.loop.call_soon_threadsafe(self._fanout, msg)


bus = EventBus()

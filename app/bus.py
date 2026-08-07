import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.models import TikTokEvent

logger = logging.getLogger("app.bus")

class EventBus:
    def __init__(self):
        self._subscribers: list[Callable[[TikTokEvent], Coroutine[Any, Any, None]]] = []

    def subscribe(self, callback: Callable[[TikTokEvent], Coroutine[Any, Any, None]]):
        """Registers a callback to receive published events."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)
            logger.debug(f"Subscribed: {callback.__name__ if hasattr(callback, '__name__') else callback}")

    def unsubscribe(self, callback: Callable[[TikTokEvent], Coroutine[Any, Any, None]]):
        """Unregisters a callback from receiving events."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
            logger.debug(f"Unsubscribed: {callback.__name__ if hasattr(callback, '__name__') else callback}")

    async def publish(self, event: TikTokEvent):
        """Publishes an event to all registered subscribers concurrently."""
        for subscriber in self._subscribers:
            try:
                await subscriber(event)
            except Exception:
                logger.exception(f"Error publishing event to subscriber {subscriber}")

# Singleton instance
event_bus = EventBus()

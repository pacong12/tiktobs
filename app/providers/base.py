from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any


class TikTokProvider(ABC):
    def __init__(self):
        # The callback function to be called when raw events are received
        # Signature: async def callback(event_type: str, raw_data: dict) -> None
        self._event_callback: Callable[[str, dict], Coroutine[Any, Any, None]] | None = None

    def set_event_callback(self, callback: Callable[[str, dict], Coroutine[Any, Any, None]]):
        """Registers a callback to handle raw events from the provider."""
        self._event_callback = callback

    async def emit_event(self, event_type: str, raw_data: dict):
        """Emits an event to the registered processor/callback."""
        if self._event_callback:
            await self._event_callback(event_type, raw_data)

    @abstractmethod
    async def connect(self, username: str) -> None:
        """Connects to the TikTok live stream of the given username."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnects from the TikTok live stream."""

    @abstractmethod
    async def is_connected(self) -> bool:
        """Returns True if currently connected to a stream, False otherwise."""

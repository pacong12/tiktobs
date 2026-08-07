from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TikTokEvent(BaseModel):
    id: str
    event_type: str
    username: str | None = None
    nickname: str | None = None
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)

"""Pydantic request schemas shared by the API routers."""

from pydantic import BaseModel


class ConnectRequest(BaseModel):
    username: str


class CandidateInput(BaseModel):
    name: str
    image_url: str | None = None
    gift_name: str | None = None


class StartPollRequest(BaseModel):
    title: str
    candidates: list[CandidateInput]
    duration_seconds: int | None = None
    round_name: str | None = None
    # When True, stored events of the current session (comments and gifts
    # that arrived before the poll started) are replayed into the poll.
    include_history: bool = False


class SettingsUpdateRequest(BaseModel):
    tiktok_sign_api_key: str | None = None


class SoundConfigRequest(BaseModel):
    gift_sound: str | None = None
    vote_sound: str | None = None
    gift_volume: float | None = None
    vote_volume: float | None = None


class TickerConfigRequest(BaseModel):
    enabled: bool | None = None
    speed: int | None = None          # pixels per second (10-300)
    direction: str | None = None      # "left" or "right"
    separator: str | None = None      # text shown between messages
    messages: list[str] | None = None  # one entry per scrolling line


class CustomGiftRequest(BaseModel):
    name: str
    diamonds: int | None = None

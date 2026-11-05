import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator

# --- Common ---

# --- Server ---

class ServerHealthResponse(BaseModel):
    connected: bool
    version: str


class ServerConfigResponse(BaseModel):
    model_config = {"extra": "allow"}
    api: Optional[bool] = None
    log_level: Optional[str] = None


class ServerConfigPatch(BaseModel):
    log_level: Optional[str] = None

# --- Paths ---

DURATION_PATTERN = re.compile(r'^(\d+h)?(\d+m)?(\d+s)?$')


def validate_duration(v: Optional[str]) -> Optional[str]:
    if v is None or v == '':
        return None
    if not DURATION_PATTERN.match(v):
        raise ValueError("Invalid duration format. Use format like '10s', '1m', '1h', '1m30s'")
    return v


class PathCreateRequest(BaseModel):
    model_config = {"populate_by_name": True}

    name: str
    source: Optional[str] = None
    source_on_demand: bool = Field(default=True, alias="sourceOnDemand")
    source_on_demand_start_timeout: Optional[str] = Field(default=None, alias="sourceOnDemandStartTimeout")
    source_on_demand_close_after: Optional[str] = Field(default=None, alias="sourceOnDemandCloseAfter")
    max_readers: Optional[int] = Field(default=None, alias="maxReaders")
    fallback: Optional[str] = None
    source_redirect: Optional[str] = Field(default=None, alias="sourceRedirect")

    @field_validator("max_readers", mode="before")
    @classmethod
    def validate_max_readers(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("max_readers must be non-negative")
        return v

    @field_validator("source_on_demand_start_timeout", "source_on_demand_close_after", mode="before")
    @classmethod
    def validate_duration_fields(cls, v: Optional[str]) -> Optional[str]:
        return validate_duration(v)


class PathPatchRequest(BaseModel):
    model_config = {"populate_by_name": True}

    source: Optional[str] = None
    source_on_demand: Optional[bool] = Field(default=None, alias="sourceOnDemand")
    source_on_demand_start_timeout: Optional[str] = Field(default=None, alias="sourceOnDemandStartTimeout")
    source_on_demand_close_after: Optional[str] = Field(default=None, alias="sourceOnDemandCloseAfter")
    max_readers: Optional[int] = Field(default=None, alias="maxReaders")
    fallback: Optional[str] = None
    source_redirect: Optional[str] = Field(default=None, alias="sourceRedirect")

    @field_validator("max_readers", mode="before")
    @classmethod
    def validate_max_readers(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("max_readers must be non-negative")
        return v

    @field_validator("source_on_demand_start_timeout", "source_on_demand_close_after", mode="before")
    @classmethod
    def validate_duration_fields(cls, v: Optional[str]) -> Optional[str]:
        return validate_duration(v)


class PathDetailResponse(BaseModel):
    name: str
    source: Optional[str] = None
    source_on_demand: bool = True
    source_on_demand_start_timeout: Optional[str] = None
    source_on_demand_close_after: Optional[str] = None
    max_readers: Optional[int] = None
    fallback: Optional[str] = None
    source_redirect: Optional[str] = None
    source_protocols: Optional[list[str]] = None
    run_on_init: Optional[str] = None
    run_on_init_restart: Optional[bool] = None

    @field_validator("source", "fallback", "source_redirect", mode="before")
    @classmethod
    def mask_password(cls, v: Optional[str]) -> Optional[str]:
        if v and "@" in v and "://" in v:

            parts = v.split("@")
            if len(parts) == 2:
                auth = parts[0]
                if ":" in auth:
                    user = auth.split(":")[0]
                    return f"{user}:***@{parts[1]}"
        return v


class PathListResponse(BaseModel):
    items: list[PathDetailResponse]

# --- Streams ---

class StreamDetailResponse(BaseModel):
    name: str
    ready: bool
    tracks: list[dict] = []
    readers: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0


class StreamListResponse(BaseModel):
    items: list[StreamDetailResponse]


class StreamSummaryResponse(BaseModel):
    total: int
    online: int
    offline: int
    total_readers: int
    total_bytes_received: int
    total_bytes_sent: int

# --- Sessions ---

class SessionDetailResponse(BaseModel):
    id: str
    type: str
    path: str
    remote_addr: str
    bytes_received: int = 0
    bytes_sent: int = 0


class SessionListResponse(BaseModel):
    items: list[SessionDetailResponse]


class SessionKickResponse(BaseModel):
    kicked: bool
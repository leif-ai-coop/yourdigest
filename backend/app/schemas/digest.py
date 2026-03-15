import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class DigestPolicyCreate(BaseModel):
    name: str = Field(max_length=200)
    schedule_cron: str = Field(max_length=100, pattern=r'^[\d\s\*\/\-\,]+$')
    target_email: str | None = None
    include_categories: list[str] | None = None
    exclude_categories: list[str] | None = None
    max_items: int = 9999
    include_weather: bool = True
    include_feeds: bool = True
    enabled: bool = True
    template: str = "default"
    digest_prompt: str | None = Field(None, max_length=10000)
    weather_prompt: str | None = Field(None, max_length=5000)
    max_tokens: int = Field(4000, ge=100, le=65536)
    since_last_any_digest: bool = False
    section_order: list[str] | None = None


class DigestPolicyUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    schedule_cron: str | None = Field(None, max_length=100)
    target_email: str | None = None
    include_categories: list[str] | None = None
    exclude_categories: list[str] | None = None
    max_items: int | None = None
    include_weather: bool | None = None
    include_feeds: bool | None = None
    enabled: bool | None = None
    template: str | None = None
    digest_prompt: str | None = Field(None, max_length=10000)
    weather_prompt: str | None = Field(None, max_length=5000)
    max_tokens: int | None = Field(None, ge=100, le=65536)
    since_last_any_digest: bool | None = None
    section_order: list[str] | None = None


class DigestPolicyResponse(BaseModel):
    id: uuid.UUID
    name: str
    schedule_cron: str
    target_email: str | None
    include_categories: list[str] | None
    exclude_categories: list[str] | None
    max_items: int
    include_weather: bool
    include_feeds: bool
    enabled: bool
    template: str
    digest_prompt: str | None
    weather_prompt: str | None
    max_tokens: int
    since_last_any_digest: bool
    section_order: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DigestSectionResponse(BaseModel):
    id: uuid.UUID
    section_type: str
    title: str
    content: str | None
    order: int
    metadata_json: dict | None

    model_config = {"from_attributes": True}


class DigestRunResponse(BaseModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    item_count: int
    html_content: str | None
    error: str | None
    created_at: datetime
    sections: list[DigestSectionResponse] = []

    model_config = {"from_attributes": True}


class DigestRunListResponse(BaseModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    item_count: int
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

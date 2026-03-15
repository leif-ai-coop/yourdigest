import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class ForwardingPolicyCreate(BaseModel):
    name: str
    description: str | None = None
    source_category: str | None = None
    target_email: str
    conditions: dict | None = None
    enabled: bool = True
    priority: int = 0


class ForwardingPolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source_category: str | None = None
    target_email: str | None = None
    conditions: dict | None = None
    enabled: bool | None = None
    priority: int | None = None


class ForwardingPolicyResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    source_category: str | None
    target_email: str
    conditions: dict | None
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WhitelistCreate(BaseModel):
    email_pattern: str
    description: str | None = None


class WhitelistResponse(BaseModel):
    id: uuid.UUID
    email_pattern: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ForwardingLogResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    policy_id: uuid.UUID
    target_email: str
    status: str
    error: str | None
    sent_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

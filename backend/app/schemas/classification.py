import uuid
from typing import Any
from datetime import datetime
from pydantic import BaseModel


class ClassificationRuleCreate(BaseModel):
    name: str
    description: str | None = None
    priority: int = 0
    conditions: dict | None = None
    category: str
    enabled: bool = True


class ClassificationRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    priority: int | None = None
    conditions: dict | None = None
    category: str | None = None
    enabled: bool | None = None


class ClassificationRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    priority: int
    conditions: dict | None
    category: str
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ClassificationOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    category: str
    confidence: float
    priority: int
    summary: str | None
    action_required: bool
    due_date: str | None
    tags: Any | None
    classified_by: str
    llm_model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

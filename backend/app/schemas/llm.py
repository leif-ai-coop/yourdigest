import uuid
from datetime import datetime
from pydantic import BaseModel


class LlmProviderConfigCreate(BaseModel):
    name: str
    provider_type: str = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str | None = None
    default_model: str
    enabled: bool = True
    extra_config: dict | None = None


class LlmProviderConfigOut(BaseModel):
    id: uuid.UUID
    name: str
    provider_type: str
    base_url: str
    default_model: str
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LlmTaskOut(BaseModel):
    id: uuid.UUID
    task_type: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    duration_ms: int
    status: str
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LlmPromptVersionCreate(BaseModel):
    task_type: str
    system_prompt: str
    user_prompt_template: str
    description: str | None = None


class LlmPromptVersionOut(BaseModel):
    id: uuid.UUID
    task_type: str
    version: int
    system_prompt: str
    user_prompt_template: str
    is_active: bool
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DraftReplyRequest(BaseModel):
    message_id: uuid.UUID
    instructions: str | None = None
    tone: str = "professional"


class DraftReplyResponse(BaseModel):
    draft: str
    model: str
    tokens_used: int
    saved_to_drafts: bool = False

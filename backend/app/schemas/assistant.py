import uuid
from datetime import datetime
from pydantic import BaseModel


class MessageSend(BaseModel):
    content: str
    conversation_id: uuid.UUID | None = None


class AssistantMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    token_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationOut):
    messages: list[AssistantMessageOut] = []

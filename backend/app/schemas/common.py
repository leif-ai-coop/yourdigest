import uuid
from datetime import datetime
from pydantic import BaseModel


class UUIDResponse(BaseModel):
    id: uuid.UUID


class MessageResponse(BaseModel):
    message: str


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int

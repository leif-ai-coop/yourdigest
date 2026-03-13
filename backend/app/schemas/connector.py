import uuid
from datetime import datetime
from pydantic import BaseModel


class ConnectorOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    description: str | None
    enabled: bool
    icon: str | None

    model_config = {"from_attributes": True}


class ConnectorInstanceCreate(BaseModel):
    connector_type: str
    name: str
    config: dict | None = None
    enabled: bool = True


class ConnectorInstanceUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None


class ConnectorInstanceOut(BaseModel):
    id: uuid.UUID
    connector_type: str
    name: str
    enabled: bool
    last_sync_at: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

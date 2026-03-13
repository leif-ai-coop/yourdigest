import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.connector import Connector, ConnectorInstance
from app.schemas.connector import ConnectorOut, ConnectorInstanceCreate, ConnectorInstanceUpdate, ConnectorInstanceOut
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.connector_service import encrypt_config, decrypt_config

router = APIRouter()


@router.get("/", response_model=list[ConnectorOut])
async def list_connectors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Connector))
    return result.scalars().all()


@router.get("/instances", response_model=list[ConnectorInstanceOut])
async def list_instances(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ConnectorInstance))
    return result.scalars().all()


@router.post("/instances", response_model=ConnectorInstanceOut, status_code=201)
async def create_instance(data: ConnectorInstanceCreate, db: AsyncSession = Depends(get_db)):
    instance = ConnectorInstance(
        connector_type=data.connector_type,
        name=data.name,
        config_encrypted=encrypt_config(data.config) if data.config else None,
        enabled=data.enabled,
    )
    db.add(instance)
    await db.flush()
    await db.refresh(instance)
    return instance


@router.get("/instances/{instance_id}", response_model=ConnectorInstanceOut)
async def get_instance(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    instance = await db.get(ConnectorInstance, instance_id)
    if not instance:
        raise NotFoundError("Connector instance not found")
    return instance


@router.patch("/instances/{instance_id}", response_model=ConnectorInstanceOut)
async def update_instance(instance_id: uuid.UUID, data: ConnectorInstanceUpdate, db: AsyncSession = Depends(get_db)):
    instance = await db.get(ConnectorInstance, instance_id)
    if not instance:
        raise NotFoundError("Connector instance not found")
    if data.name is not None:
        instance.name = data.name
    if data.config is not None:
        instance.config_encrypted = encrypt_config(data.config)
    if data.enabled is not None:
        instance.enabled = data.enabled
    await db.flush()
    await db.refresh(instance)
    return instance


@router.delete("/instances/{instance_id}", response_model=MessageResponse)
async def delete_instance(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    instance = await db.get(ConnectorInstance, instance_id)
    if not instance:
        raise NotFoundError("Connector instance not found")
    await db.delete(instance)
    return MessageResponse(message="Deleted")

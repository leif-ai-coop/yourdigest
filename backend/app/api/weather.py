import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.weather import WeatherSource, WeatherSnapshot
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.weather_service import fetch_weather

router = APIRouter()


class WeatherSourceCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    enabled: bool = True


class WeatherSourceUpdate(BaseModel):
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    enabled: bool | None = None


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WeatherSource).order_by(WeatherSource.created_at))
    return result.scalars().all()


@router.post("/sources", status_code=201)
async def add_source(data: WeatherSourceCreate, db: AsyncSession = Depends(get_db)):
    source = WeatherSource(**data.model_dump())
    db.add(source)
    await db.flush()

    # Immediately fetch weather
    await fetch_weather(db, source)
    await db.refresh(source)
    return source


@router.put("/sources/{source_id}")
async def update_source(source_id: uuid.UUID, data: WeatherSourceUpdate, db: AsyncSession = Depends(get_db)):
    source = await db.get(WeatherSource, source_id)
    if not source:
        raise NotFoundError("Weather source not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    await db.flush()
    await db.refresh(source)
    return source


@router.delete("/sources/{source_id}", response_model=MessageResponse)
async def delete_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    source = await db.get(WeatherSource, source_id)
    if not source:
        raise NotFoundError("Weather source not found")
    await db.delete(source)
    return MessageResponse(message="Weather source deleted")


@router.post("/sources/{source_id}/sync")
async def sync_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    source = await db.get(WeatherSource, source_id)
    if not source:
        raise NotFoundError("Weather source not found")
    snapshot = await fetch_weather(db, source)
    if not snapshot:
        return {"error": "Fetch failed"}
    return {"summary": snapshot.summary}


@router.get("/latest")
async def latest_snapshot(source_name: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(WeatherSnapshot).order_by(desc(WeatherSnapshot.created_at)).limit(1)
    if source_name:
        query = query.where(WeatherSnapshot.source_name == source_name)
    result = await db.execute(query)
    return result.scalar_one_or_none()

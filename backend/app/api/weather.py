from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.weather import WeatherSource, WeatherSnapshot

router = APIRouter()


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WeatherSource))
    return result.scalars().all()


@router.get("/latest")
async def latest_snapshot(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WeatherSnapshot).order_by(desc(WeatherSnapshot.created_at)).limit(1))
    return result.scalar_one_or_none()

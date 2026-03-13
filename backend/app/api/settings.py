from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.audit import AppSetting
from app.schemas.common import MessageResponse

router = APIRouter()


@router.get("/")
async def list_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AppSetting))
    return result.scalars().all()


@router.put("/{key}", response_model=MessageResponse)
async def set_setting(key: str, value: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
        db.add(setting)
    return MessageResponse(message=f"Setting '{key}' updated")

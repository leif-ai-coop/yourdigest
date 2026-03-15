import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.audit import AppSetting
from app.schemas.common import MessageResponse
from app.llm.prompt_registry import DEFAULT_CATEGORIES

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


# --- Categories ---

@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    """Get configured mail categories."""
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "categories")
    )
    setting = result.scalar_one_or_none()
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            pass
    return DEFAULT_CATEGORIES


class CategoriesUpdate(BaseModel):
    categories: dict[str, str]


class DigestThresholds(BaseModel):
    detail_threshold: int = 50
    compact_threshold: int = 200


@router.put("/categories")
async def set_categories(data: CategoriesUpdate, db: AsyncSession = Depends(get_db)):
    """Set mail categories. Keys are category names, values are descriptions."""
    value = json.dumps(data.categories)
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "categories")
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key="categories", value=value)
        db.add(setting)
    return data.categories


# --- Digest Thresholds ---

@router.get("/digest-thresholds")
async def get_digest_thresholds(db: AsyncSession = Depends(get_db)):
    """Get digest display thresholds."""
    thresholds = {"detail_threshold": 50, "compact_threshold": 200}
    for key in ["digest_detail_threshold", "digest_compact_threshold"]:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            try:
                field = key.replace("digest_", "")
                thresholds[field] = int(setting.value)
            except ValueError:
                pass
    return thresholds


@router.put("/digest-thresholds")
async def set_digest_thresholds(data: DigestThresholds, db: AsyncSession = Depends(get_db)):
    """Set digest display thresholds."""
    for key, value in [
        ("digest_detail_threshold", data.detail_threshold),
        ("digest_compact_threshold", data.compact_threshold),
    ]:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    return {"detail_threshold": data.detail_threshold, "compact_threshold": data.compact_threshold}


# --- Assistant Settings ---

class AssistantSettings(BaseModel):
    browse_days: int = 7
    browse_limit: int = 50
    body_max_chars: int = 3000


@router.get("/assistant")
async def get_assistant_settings(db: AsyncSession = Depends(get_db)):
    """Get assistant chat settings."""
    defaults = AssistantSettings()
    settings = {}
    for key in ["assistant_browse_days", "assistant_browse_limit", "assistant_body_max_chars"]:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            try:
                field = key.replace("assistant_", "")
                settings[field] = int(setting.value)
            except ValueError:
                pass
    return {**defaults.model_dump(), **settings}


@router.put("/assistant")
async def set_assistant_settings(data: AssistantSettings, db: AsyncSession = Depends(get_db)):
    """Set assistant chat settings."""
    for key, value in [
        ("assistant_browse_days", data.browse_days),
        ("assistant_browse_limit", data.browse_limit),
        ("assistant_body_max_chars", data.body_max_chars),
    ]:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    return data.model_dump()

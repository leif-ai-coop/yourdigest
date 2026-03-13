from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.assistant import AssistantConversation

router = APIRouter()


@router.get("/conversations")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AssistantConversation).order_by(AssistantConversation.created_at.desc()).limit(50))
    return result.scalars().all()

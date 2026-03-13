import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.forwarding import ForwardingPolicy, ForwardingWhitelist, ForwardingLog
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError

router = APIRouter()


@router.get("/policies")
async def list_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ForwardingPolicy))
    return result.scalars().all()


@router.post("/policies", status_code=201)
async def create_policy(name: str, target_email: str, source_category: str | None = None, db: AsyncSession = Depends(get_db)):
    policy = ForwardingPolicy(name=name, target_email=target_email, source_category=source_category)
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    return policy


@router.delete("/policies/{policy_id}", response_model=MessageResponse)
async def delete_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    policy = await db.get(ForwardingPolicy, policy_id)
    if not policy:
        raise NotFoundError("Policy not found")
    await db.delete(policy)
    return MessageResponse(message="Policy deleted")


@router.get("/whitelist")
async def list_whitelist(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ForwardingWhitelist))
    return result.scalars().all()


@router.get("/log")
async def list_forwarding_logs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ForwardingLog).order_by(ForwardingLog.created_at.desc()).limit(100))
    return result.scalars().all()

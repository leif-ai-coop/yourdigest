import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.forwarding import ForwardingPolicy, ForwardingWhitelist, ForwardingLog
from app.schemas.forwarding import (
    ForwardingPolicyCreate, ForwardingPolicyUpdate, ForwardingPolicyResponse,
    WhitelistCreate, WhitelistResponse,
    ForwardingLogResponse,
)
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError, ConflictError
from app.services.forwarding_service import process_forwarding

router = APIRouter()


# --- Policies ---

@router.get("/policies", response_model=list[ForwardingPolicyResponse])
async def list_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ForwardingPolicy).order_by(ForwardingPolicy.priority.desc())
    )
    return result.scalars().all()


@router.post("/policies", response_model=ForwardingPolicyResponse, status_code=201)
async def create_policy(data: ForwardingPolicyCreate, db: AsyncSession = Depends(get_db)):
    policy = ForwardingPolicy(**data.model_dump())
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    return policy


@router.put("/policies/{policy_id}", response_model=ForwardingPolicyResponse)
async def update_policy(
    policy_id: uuid.UUID, data: ForwardingPolicyUpdate, db: AsyncSession = Depends(get_db)
):
    policy = await db.get(ForwardingPolicy, policy_id)
    if not policy:
        raise NotFoundError("Policy not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(policy, key, value)
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


@router.post("/policies/{policy_id}/test", response_model=MessageResponse)
async def test_policy(policy_id: uuid.UUID, message_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Test a policy against a specific message (dry run, then forward)."""
    policy = await db.get(ForwardingPolicy, policy_id)
    if not policy:
        raise NotFoundError("Policy not found")

    from app.models.mail import MailMessage
    message = await db.get(MailMessage, message_id)
    if not message:
        raise NotFoundError("Message not found")

    from app.services.forwarding_service import forward_message
    log = await forward_message(db, message, policy)
    return MessageResponse(message=f"Forwarding {log.status}: {log.error or 'success'}")


# --- Whitelist ---

@router.get("/whitelist", response_model=list[WhitelistResponse])
async def list_whitelist(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ForwardingWhitelist))
    return result.scalars().all()


@router.post("/whitelist", response_model=WhitelistResponse, status_code=201)
async def add_whitelist(data: WhitelistCreate, db: AsyncSession = Depends(get_db)):
    # Check for duplicates
    existing = await db.execute(
        select(ForwardingWhitelist).where(
            ForwardingWhitelist.email_pattern == data.email_pattern
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Pattern already exists")

    entry = ForwardingWhitelist(**data.model_dump())
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


@router.delete("/whitelist/{entry_id}", response_model=MessageResponse)
async def delete_whitelist(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    entry = await db.get(ForwardingWhitelist, entry_id)
    if not entry:
        raise NotFoundError("Whitelist entry not found")
    await db.delete(entry)
    return MessageResponse(message="Whitelist entry deleted")


# --- Logs ---

@router.get("/log", response_model=list[ForwardingLogResponse])
async def list_forwarding_logs(
    status: str | None = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(ForwardingLog).order_by(ForwardingLog.created_at.desc())
    if status:
        query = query.where(ForwardingLog.status == status)
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# --- Manual trigger ---

@router.post("/forward/{message_id}")
async def forward_message_manual(message_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Manually trigger forwarding for a message."""
    logs = await process_forwarding(db, message_id)
    if not logs:
        return {"message": "No matching policies found", "forwarded": 0}
    results = [{"policy_id": str(l.policy_id), "target": l.target_email, "status": l.status} for l in logs]
    return {"message": f"Forwarded to {len(logs)} targets", "forwarded": len(logs), "results": results}

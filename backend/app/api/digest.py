import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.digest import DigestPolicy, DigestRun
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError

router = APIRouter()


@router.get("/policies")
async def list_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DigestPolicy))
    return result.scalars().all()


@router.get("/runs")
async def list_runs(policy_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    query = select(DigestRun).order_by(desc(DigestRun.created_at)).limit(50)
    if policy_id:
        query = query.where(DigestRun.policy_id == policy_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    run = await db.get(DigestRun, run_id)
    if not run:
        raise NotFoundError("Digest run not found")
    return run

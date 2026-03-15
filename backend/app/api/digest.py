import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.digest import DigestPolicy, DigestRun, DigestSection
from app.schemas.digest import (
    DigestPolicyCreate, DigestPolicyUpdate, DigestPolicyResponse,
    DigestRunResponse, DigestRunListResponse,
)
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.digest_service import compose_digest, HEALTH_CHART_CONFIG, HEALTH_DATA_TYPE_LABELS

router = APIRouter()


@router.get("/health-options")
async def get_health_options():
    """Return available health chart IDs and data types for digest settings."""
    charts = [{"id": k, "label": v["label"]} for k, v in HEALTH_CHART_CONFIG.items()]
    data_types = [{"id": k, "label": v} for k, v in HEALTH_DATA_TYPE_LABELS.items()]
    return {"charts": charts, "data_types": data_types}


# --- Policies ---

@router.get("/policies", response_model=list[DigestPolicyResponse])
async def list_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DigestPolicy))
    return result.scalars().all()


@router.post("/policies", response_model=DigestPolicyResponse, status_code=201)
async def create_policy(data: DigestPolicyCreate, db: AsyncSession = Depends(get_db)):
    import json
    dump = data.model_dump()
    if dump.get("section_order") and isinstance(dump["section_order"], list):
        dump["section_order"] = json.dumps(dump["section_order"])
    policy = DigestPolicy(**dump)
    db.add(policy)
    await db.flush()
    await db.refresh(policy)

    # Reload scheduler to pick up new policy
    try:
        from app.worker.scheduler import reload_digest_schedules
        await reload_digest_schedules()
    except Exception:
        pass

    return policy


@router.put("/policies/{policy_id}", response_model=DigestPolicyResponse)
async def update_policy(
    policy_id: uuid.UUID, data: DigestPolicyUpdate, db: AsyncSession = Depends(get_db)
):
    policy = await db.get(DigestPolicy, policy_id)
    if not policy:
        raise NotFoundError("Digest policy not found")
    import json
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "section_order" and isinstance(value, list):
            value = json.dumps(value)
        setattr(policy, key, value)
    await db.flush()
    await db.refresh(policy)

    try:
        from app.worker.scheduler import reload_digest_schedules
        await reload_digest_schedules()
    except Exception:
        pass

    return policy


@router.delete("/policies/{policy_id}", response_model=MessageResponse)
async def delete_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    policy = await db.get(DigestPolicy, policy_id)
    if not policy:
        raise NotFoundError("Digest policy not found")
    await db.delete(policy)

    try:
        from app.worker.scheduler import reload_digest_schedules
        await reload_digest_schedules()
    except Exception:
        pass

    return MessageResponse(message="Digest policy deleted")


# --- Runs ---

@router.get("/runs", response_model=list[DigestRunListResponse])
async def list_runs(policy_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    query = select(DigestRun).order_by(desc(DigestRun.created_at)).limit(50)
    if policy_id:
        query = query.where(DigestRun.policy_id == policy_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/runs/{run_id}", response_model=DigestRunResponse)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DigestRun)
        .options(selectinload(DigestRun.sections))
        .where(DigestRun.id == run_id)
    )
    run = result.scalars().first()
    if not run:
        raise NotFoundError("Digest run not found")
    return run


# --- Manual trigger ---

@router.post("/policies/{policy_id}/run", response_model=DigestRunListResponse)
async def trigger_run(
    policy_id: uuid.UUID,
    since_hours: int | None = None,
    cross: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a digest run for a policy.

    Optional since_hours overrides the default "since last run" behavior.
    If cross=true, uses the last run of ANY policy as start point.
    """
    policy = await db.get(DigestPolicy, policy_id)
    if not policy:
        raise NotFoundError("Digest policy not found")

    override_since = None
    if since_hours is not None:
        from datetime import datetime, timezone, timedelta
        override_since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    elif cross:
        # Find last completed run of ANY policy
        from datetime import datetime, timezone, timedelta
        last_any = await db.execute(
            select(DigestRun.completed_at)
            .where(DigestRun.status == "completed")
            .order_by(desc(DigestRun.completed_at))
            .limit(1)
        )
        last_completed = last_any.scalar_one_or_none()
        override_since = last_completed if last_completed else datetime.now(timezone.utc) - timedelta(hours=24)

    run = await compose_digest(db, policy, override_since=override_since)
    await db.commit()
    return run


# --- Preview ---

@router.get("/runs/{run_id}/html")
async def get_run_html(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get the HTML content of a digest run for preview."""
    run = await db.get(DigestRun, run_id)
    if not run:
        raise NotFoundError("Digest run not found")
    if not run.html_content:
        raise NotFoundError("No HTML content available for this run")

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=run.html_content)

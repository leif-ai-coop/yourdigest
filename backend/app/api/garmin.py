import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.garmin import GarminAccount, GarminSnapshot
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.connector_service import encrypt_value
from app.services.garmin_service import (
    DATA_TYPES,
    sync_day,
    sync_range,
    test_login,
)

router = APIRouter()


class GarminAccountCreate(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=500)
    enabled: bool = True


class GarminAccountResponse(BaseModel):
    id: uuid.UUID
    email: str
    enabled: bool
    last_sync_at: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


class GarminSyncRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


@router.get("/types")
async def list_types():
    """List available Garmin data types."""
    return DATA_TYPES


@router.get("/account")
async def get_account(db: AsyncSession = Depends(get_db)):
    """Get the Garmin account (without password)."""
    result = await db.execute(select(GarminAccount).limit(1))
    account = result.scalar_one_or_none()
    if not account:
        raise NotFoundError("No Garmin account configured")
    return {
        "id": account.id,
        "email": account.email,
        "enabled": account.enabled,
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
        "last_error": account.last_error,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }


@router.post("/account", status_code=201)
async def create_or_update_account(data: GarminAccountCreate, db: AsyncSession = Depends(get_db)):
    """Create or update the Garmin account."""
    result = await db.execute(select(GarminAccount).limit(1))
    account = result.scalar_one_or_none()

    encrypted_pw = encrypt_value(data.password)

    if account:
        account.email = data.email
        account.password_encrypted = encrypted_pw
        account.enabled = data.enabled
        account.last_error = None
    else:
        account = GarminAccount(
            email=data.email,
            password_encrypted=encrypted_pw,
            enabled=data.enabled,
        )
        db.add(account)

    await db.flush()
    await db.refresh(account)
    return {
        "id": account.id,
        "email": account.email,
        "enabled": account.enabled,
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
        "last_error": account.last_error,
    }


@router.post("/account/test")
async def test_account(db: AsyncSession = Depends(get_db)):
    """Test login for the configured Garmin account."""
    result = await db.execute(select(GarminAccount).limit(1))
    account = result.scalar_one_or_none()
    if not account:
        raise NotFoundError("No Garmin account configured")

    from app.services.connector_service import decrypt_value
    password = decrypt_value(account.password_encrypted)
    success, message = await test_login(account.email, password, str(account.id))

    if not success:
        account.last_error = message

    return {"success": success, "message": message}


@router.delete("/account", response_model=MessageResponse)
async def delete_account(db: AsyncSession = Depends(get_db)):
    """Delete the Garmin account and all associated data."""
    result = await db.execute(select(GarminAccount).limit(1))
    account = result.scalar_one_or_none()
    if not account:
        raise NotFoundError("No Garmin account configured")
    await db.delete(account)
    return MessageResponse(message="Garmin account deleted")


@router.post("/sync")
async def trigger_sync(
    data: GarminSyncRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger manual sync. Optional days parameter for backfill (default 7)."""
    result = await db.execute(
        select(GarminAccount).where(GarminAccount.enabled == True)
    )
    accounts = result.scalars().all()
    if not accounts:
        raise NotFoundError("No enabled Garmin account found")

    days = data.days if data else 7
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    total = 0
    for account in accounts:
        count = await sync_range(db, account, start_date, end_date)
        total += count

    return {"message": f"Synced {total} snapshots for {len(accounts)} account(s)", "snapshots": total}


@router.get("/data/{data_type}")
async def get_data_by_type(
    data_type: str,
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get snapshots for a specific data type within a date range."""
    if data_type not in DATA_TYPES:
        raise NotFoundError(f"Unknown data type: {data_type}. Available: {DATA_TYPES}")

    if not start_date:
        start_date = date.today() - timedelta(days=7)
    if not end_date:
        end_date = date.today()

    query = (
        select(GarminSnapshot)
        .where(
            and_(
                GarminSnapshot.data_type == data_type,
                GarminSnapshot.date >= start_date,
                GarminSnapshot.date <= end_date,
            )
        )
        .order_by(GarminSnapshot.date.asc())
    )

    result = await db.execute(query)
    snapshots = result.scalars().all()
    return [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "data_type": s.data_type,
            "data": s.data,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]


@router.get("/data")
async def get_all_data(
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get all data types for a date range, grouped by data_type. Auto-syncs missing days."""
    if not start_date:
        start_date = date.today() - timedelta(days=7)
    if not end_date:
        end_date = date.today()

    query = (
        select(GarminSnapshot)
        .where(
            and_(
                GarminSnapshot.date >= start_date,
                GarminSnapshot.date <= end_date,
            )
        )
        .order_by(GarminSnapshot.date.asc())
    )

    result = await db.execute(query)
    snapshots = result.scalars().all()

    grouped: dict[str, list] = {}
    for s in snapshots:
        if s.data_type not in grouped:
            grouped[s.data_type] = []
        grouped[s.data_type].append({
            "id": s.id,
            "date": s.date.isoformat(),
            "data": s.data,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return grouped

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.depot import DepotPosition, DepotSnapshot
from app.schemas.common import MessageResponse
from app.schemas.depot import (
    DepotPositionCreate, DepotPositionUpdate, DepotPositionOut,
    DepotOverview, DepotTotals, DepotSnapshotOut,
    ImportRequest, ImportPreview, ImportPreviewItem, ApplyRequest,
)
from app.exceptions import NotFoundError
from app.services import depot_service

router = APIRouter()


@router.get("/positions", response_model=DepotOverview)
async def overview(db: AsyncSession = Depends(get_db)):
    positions = (await db.execute(
        select(DepotPosition)
        .where(DepotPosition.is_active == True)  # noqa: E712
        .order_by(desc(DepotPosition.last_value))
    )).scalars().all()
    totals = await depot_service.compute_totals(db)
    return DepotOverview(
        totals=DepotTotals(**totals),
        positions=[DepotPositionOut.model_validate(p) for p in positions],
    )


@router.post("/positions", response_model=DepotPositionOut, status_code=201)
async def add_position(data: DepotPositionCreate, db: AsyncSession = Depends(get_db)):
    pos = DepotPosition(**data.model_dump())
    if pos.last_value is None and pos.quantity is not None and pos.last_price is not None:
        pos.last_value = float(pos.quantity) * float(pos.last_price)
    if pos.last_price is not None:
        pos.last_price_at = datetime.now(timezone.utc)
    db.add(pos)
    await db.flush()
    await depot_service._create_snapshot(db, source="screenshot")
    await db.refresh(pos)
    return DepotPositionOut.model_validate(pos)


@router.put("/positions/{position_id}", response_model=DepotPositionOut)
async def update_position(position_id: uuid.UUID, data: DepotPositionUpdate, db: AsyncSession = Depends(get_db)):
    pos = await db.get(DepotPosition, position_id)
    if not pos:
        raise NotFoundError("Position not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(pos, key, value)
    if pos.quantity is not None and pos.last_price is not None:
        pos.last_value = float(pos.quantity) * float(pos.last_price)
    await db.flush()
    await db.refresh(pos)
    return DepotPositionOut.model_validate(pos)


@router.delete("/positions/{position_id}", response_model=MessageResponse)
async def delete_position(position_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    pos = await db.get(DepotPosition, position_id)
    if not pos:
        raise NotFoundError("Position not found")
    await db.delete(pos)
    return MessageResponse(message="Position geloescht")


@router.post("/import-screenshot", response_model=ImportPreview)
async def import_screenshot(data: ImportRequest, db: AsyncSession = Depends(get_db)):
    """OCR des Screenshots -> Vorschau (kein Auto-Commit)."""
    parsed = await depot_service.parse_screenshot(data.image, data.model)
    items = await depot_service.build_preview(db, parsed["positions"])
    warning = None
    if not parsed["positions"]:
        warning = "Keine Positionen erkannt. Anderes Vision-Modell oder schaerferen Screenshot probieren."
    return ImportPreview(
        items=[ImportPreviewItem(**i) for i in items],
        parsed_total_value=parsed.get("total_value"),
        model_used=parsed.get("model"),
        warning=warning,
    )


@router.post("/apply-import", response_model=DepotOverview)
async def apply_import(data: ApplyRequest, db: AsyncSession = Depends(get_db)):
    await depot_service.apply_positions(db, data.positions, replace_missing=data.replace_missing)
    return await overview(db)


@router.post("/refresh-prices", response_model=DepotOverview)
async def refresh_prices(db: AsyncSession = Depends(get_db)):
    await depot_service.refresh_prices(db)
    return await overview(db)


@router.get("/snapshots", response_model=list[DepotSnapshotOut])
async def list_snapshots(
    limit: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(DepotSnapshot).order_by(desc(DepotSnapshot.captured_at)).limit(limit)
    )).scalars().all()
    return [DepotSnapshotOut.model_validate(r) for r in reversed(rows)]

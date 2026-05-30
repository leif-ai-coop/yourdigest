import uuid
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class DepotPositionBase(BaseModel):
    name: str = Field(..., max_length=300)
    isin: str | None = Field(None, max_length=20)
    wkn: str | None = Field(None, max_length=20)
    quantity: float = Field(0, ge=0)
    avg_buy_price: float | None = Field(None, ge=0)
    currency: str = Field("EUR", max_length=3)


class DepotPositionCreate(DepotPositionBase):
    last_price: float | None = Field(None, ge=0)
    last_value: float | None = Field(None, ge=0)
    day_change_pct: float | None = None
    total_change_pct: float | None = None
    source: str = Field("manual", max_length=20)


class DepotPositionUpdate(BaseModel):
    name: str | None = Field(None, max_length=300)
    isin: str | None = Field(None, max_length=20)
    wkn: str | None = Field(None, max_length=20)
    quantity: float | None = Field(None, ge=0)
    avg_buy_price: float | None = Field(None, ge=0)
    last_price: float | None = Field(None, ge=0)
    is_active: bool | None = None


class DepotPositionOut(DepotPositionBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    last_price: float | None = None
    last_value: float | None = None
    last_price_at: datetime | None = None
    day_change_pct: float | None = None
    total_change_pct: float | None = None
    market_symbol: str | None = None
    price_stale: bool = False
    source: str
    is_active: bool
    updated_at: datetime


class DepotTotals(BaseModel):
    total_value: float = 0
    total_cost: float | None = None
    total_gain: float | None = None
    total_gain_pct: float | None = None
    day_change_value: float | None = None
    position_count: int = 0
    currency: str = "EUR"
    last_update: datetime | None = None
    has_stale_prices: bool = False


class DepotOverview(BaseModel):
    totals: DepotTotals
    positions: list[DepotPositionOut]


class DepotSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    captured_at: datetime
    total_value: float | None = None
    total_cost: float | None = None
    currency: str
    source: str
    note: str | None = None


# --- Screenshot-Import ---

class ParsedPosition(BaseModel):
    name: str = Field("", max_length=300)
    isin: str | None = Field(None, max_length=20)
    wkn: str | None = Field(None, max_length=20)
    quantity: float | None = Field(None, ge=0)
    avg_buy_price: float | None = Field(None, ge=0)
    last_price: float | None = Field(None, ge=0)
    last_value: float | None = Field(None, ge=0)
    day_change_pct: float | None = None
    total_change_pct: float | None = None
    currency: str | None = Field(None, max_length=3)


class ImportPreviewItem(BaseModel):
    parsed: ParsedPosition
    match_id: uuid.UUID | None = None          # existierende Position, falls Match
    match_name: str | None = None
    status: str                                 # new | update | unchanged


class ImportPreview(BaseModel):
    items: list[ImportPreviewItem]
    parsed_total_value: float | None = None
    model_used: str | None = None
    warning: str | None = None


class ImportRequest(BaseModel):
    image: str = Field(..., description="Data-URL oder Base64 des Screenshots")
    model: str | None = Field(None, max_length=120)


class ImportHtmlRequest(BaseModel):
    html: str = Field(..., max_length=5_000_000, description="ING-Depotuebersicht Seitenquelltext")


class ApplyRequest(BaseModel):
    positions: list[ParsedPosition]
    replace_missing: bool = Field(
        False, description="Positionen, die im Screenshot fehlen, deaktivieren"
    )
    source: str = Field("screenshot", max_length=20, description="screenshot|quelltext|manual")


class DuplicateGroupOut(BaseModel):
    key: str
    ids: list[uuid.UUID]
    names: list[str]


class DuplicatesOut(BaseModel):
    count: int
    groups: list[DuplicateGroupOut]

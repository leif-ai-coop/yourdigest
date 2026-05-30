import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, JSON, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class DepotPosition(Base, UUIDMixin, TimestampMixin):
    """Eine aktuelle Position im Depot (ein Wertpapier)."""
    __tablename__ = "depot_position"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    wkn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    avg_buy_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # Aktueller Stand
    last_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    last_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    last_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    day_change_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    total_change_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Marktdaten-Mapping (ISIN -> Symbol), gecached
    market_symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    price_stale: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[str] = mapped_column(String(20), nullable=False, default="screenshot")  # screenshot|manual|market
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DepotSnapshot(Base, UUIDMixin, TimestampMixin):
    """Zeitpunkt-Aufnahme des Gesamtdepots (fuer Wertverlauf)."""
    __tablename__ = "depot_snapshot"

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    positions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="screenshot")  # screenshot|market
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

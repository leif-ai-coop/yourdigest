from sqlalchemy import String, Float, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class WeatherSource(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "weather_source"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="openmeteo")
    enabled: Mapped[bool] = mapped_column(default=True)


class WeatherSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "weather_snapshot"

    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

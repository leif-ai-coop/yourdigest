import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weather import WeatherSource, WeatherSnapshot

logger = logging.getLogger(__name__)

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: ("Klar", "clear"),
    1: ("Überwiegend klar", "mostly_clear"),
    2: ("Teilweise bewölkt", "partly_cloudy"),
    3: ("Bewölkt", "cloudy"),
    45: ("Nebel", "fog"),
    48: ("Nebel mit Reif", "fog"),
    51: ("Leichter Nieselregen", "drizzle"),
    53: ("Nieselregen", "drizzle"),
    55: ("Starker Nieselregen", "drizzle"),
    56: ("Gefrierender Nieselregen", "drizzle"),
    57: ("Starker gefr. Nieselregen", "drizzle"),
    61: ("Leichter Regen", "rain"),
    63: ("Regen", "rain"),
    65: ("Starker Regen", "heavy_rain"),
    66: ("Gefrierender Regen", "rain"),
    67: ("Starker gefr. Regen", "heavy_rain"),
    71: ("Leichter Schneefall", "snow"),
    73: ("Schneefall", "snow"),
    75: ("Starker Schneefall", "snow"),
    77: ("Schneegriesel", "snow"),
    80: ("Leichte Regenschauer", "rain"),
    81: ("Regenschauer", "rain"),
    82: ("Starke Regenschauer", "heavy_rain"),
    85: ("Leichte Schneeschauer", "snow"),
    86: ("Starke Schneeschauer", "snow"),
    95: ("Gewitter", "thunderstorm"),
    96: ("Gewitter mit Hagel", "thunderstorm"),
    99: ("Gewitter mit starkem Hagel", "thunderstorm"),
}


def get_weather_icon_type(code: int) -> str:
    """Map weather code to icon type."""
    return WEATHER_CODES.get(code, ("Unbekannt", "clear"))[1]


def get_weather_description(code: int) -> str:
    """Map weather code to German description."""
    return WEATHER_CODES.get(code, ("Unbekannt", "clear"))[0]


async def fetch_weather(db: AsyncSession, source: WeatherSource) -> WeatherSnapshot | None:
    """Fetch detailed weather data from OpenMeteo for a source."""
    try:
        params = {
            "latitude": source.latitude,
            "longitude": source.longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
            "hourly": "temperature_2m,weather_code,precipitation_probability,precipitation,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weather_code,sunrise,sunset,uv_index_max,wind_speed_10m_max",
            "timezone": "Europe/Berlin",
            "forecast_days": 4,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(OPENMETEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current", {})
        hourly = data.get("hourly", {})
        daily = data.get("daily", {})

        # Build day periods from hourly data (today only)
        # Morning: 6-9, Midday: 10-13, Afternoon: 14-17, Evening: 18-21
        periods = []
        period_defs = [
            ("Morgen", 6, 9),
            ("Mittag", 10, 13),
            ("Nachmittag", 14, 17),
            ("Abend", 18, 21),
        ]

        hourly_times = hourly.get("time", [])
        hourly_temps = hourly.get("temperature_2m", [])
        hourly_codes = hourly.get("weather_code", [])
        hourly_precip_prob = hourly.get("precipitation_probability", [])
        hourly_precip = hourly.get("precipitation", [])
        hourly_wind = hourly.get("wind_speed_10m", [])

        for period_name, h_start, h_end in period_defs:
            temps = []
            codes = []
            precip_probs = []
            precip_sums = []
            winds = []

            for i, t in enumerate(hourly_times):
                try:
                    hour = int(t.split("T")[1].split(":")[0])
                    # Only today's data (first 24 entries)
                    if i < 24 and h_start <= hour <= h_end:
                        if i < len(hourly_temps): temps.append(hourly_temps[i])
                        if i < len(hourly_codes): codes.append(hourly_codes[i])
                        if i < len(hourly_precip_prob): precip_probs.append(hourly_precip_prob[i])
                        if i < len(hourly_precip): precip_sums.append(hourly_precip[i])
                        if i < len(hourly_wind): winds.append(hourly_wind[i])
                except (IndexError, ValueError):
                    continue

            if temps:
                # Use the most severe weather code for the period
                dominant_code = max(codes) if codes else 0
                periods.append({
                    "name": period_name,
                    "temp_avg": round(sum(temps) / len(temps), 1),
                    "temp_min": round(min(temps), 1),
                    "temp_max": round(max(temps), 1),
                    "weather_code": dominant_code,
                    "weather_desc": get_weather_description(dominant_code),
                    "icon_type": get_weather_icon_type(dominant_code),
                    "precip_probability": round(max(precip_probs)) if precip_probs else 0,
                    "precipitation": round(sum(precip_sums), 1) if precip_sums else 0,
                    "wind_avg": round(sum(winds) / len(winds), 1) if winds else 0,
                })

        # Build daily forecast
        forecast_days = []
        if daily.get("time"):
            for i, date in enumerate(daily["time"]):
                if i == 0:
                    continue  # Skip today, covered by periods
                code = daily.get("weather_code", [0])[i] if i < len(daily.get("weather_code", [])) else 0
                forecast_days.append({
                    "date": date,
                    "temp_min": daily.get("temperature_2m_min", [None])[i],
                    "temp_max": daily.get("temperature_2m_max", [None])[i],
                    "weather_code": code,
                    "weather_desc": get_weather_description(code),
                    "icon_type": get_weather_icon_type(code),
                    "precipitation_sum": daily.get("precipitation_sum", [0])[i],
                    "precip_probability": daily.get("precipitation_probability_max", [0])[i],
                    "wind_max": daily.get("wind_speed_10m_max", [0])[i],
                    "uv_index": daily.get("uv_index_max", [0])[i],
                    "sunrise": daily.get("sunrise", [""])[i],
                    "sunset": daily.get("sunset", [""])[i],
                })

        # Build structured result
        structured = {
            "location": source.name,
            "current": {
                "temp": current.get("temperature_2m"),
                "feels_like": current.get("apparent_temperature"),
                "humidity": current.get("relative_humidity_2m"),
                "wind": current.get("wind_speed_10m"),
                "precipitation": current.get("precipitation"),
                "weather_code": current.get("weather_code", 0),
                "weather_desc": get_weather_description(current.get("weather_code", 0)),
                "icon_type": get_weather_icon_type(current.get("weather_code", 0)),
            },
            "today_periods": periods,
            "forecast": forecast_days,
        }

        # Build text summary for legacy/simple use
        summary_parts = [
            f"Aktuell in {source.name}: {structured['current']['temp']}°C ({structured['current']['weather_desc']})",
            f"Gefühlt: {structured['current']['feels_like']}°C, Wind: {structured['current']['wind']} km/h",
        ]
        for p in periods:
            summary_parts.append(
                f"{p['name']}: {p['temp_avg']}°C, {p['weather_desc']}"
                + (f", {p['precip_probability']}% Regen" if p['precip_probability'] > 20 else "")
            )
        for d in forecast_days:
            summary_parts.append(
                f"{d['date']}: {d['temp_min']}–{d['temp_max']}°C, {d['weather_desc']}"
                + (f", {d['precipitation_sum']}mm" if d['precipitation_sum'] and d['precipitation_sum'] > 0 else "")
            )

        snapshot = WeatherSnapshot(
            source_name=source.name,
            data=structured,
            summary="\n".join(summary_parts),
        )
        db.add(snapshot)
        return snapshot

    except Exception as e:
        logger.error(f"Weather fetch failed for {source.name}: {e}")
        return None


async def fetch_all_weather(db: AsyncSession) -> int:
    """Fetch weather for all enabled sources. Returns count of snapshots created."""
    result = await db.execute(
        select(WeatherSource).where(WeatherSource.enabled == True)
    )
    sources = result.scalars().all()

    count = 0
    for source in sources:
        snapshot = await fetch_weather(db, source)
        if snapshot:
            logger.info(f"Weather updated for '{source.name}'")
            count += 1

    return count

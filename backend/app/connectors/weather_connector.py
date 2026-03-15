import httpx
from app.connectors.base import BaseConnector


class WeatherConnector(BaseConnector):
    @property
    def connector_type(self) -> str:
        return "weather"

    @property
    def display_name(self) -> str:
        return "Weather (OpenMeteo)"

    async def test_connection(self, config: dict) -> str:
        lat = config.get("latitude")
        lon = config.get("longitude")
        if not lat or not lon:
            return "Error: latitude and longitude required"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={"latitude": lat, "longitude": lon, "current": "temperature_2m"},
                )
                resp.raise_for_status()
                data = resp.json()
            temp = data.get("current", {}).get("temperature_2m", "?")
            return f"OK: {temp}°C at ({lat}, {lon})"
        except Exception as e:
            return f"Error: {e}"

    async def fetch(self, config: dict) -> list[dict]:
        return []

from app.connectors.base import BaseConnector


class WeatherConnector(BaseConnector):
    @property
    def connector_type(self) -> str:
        return "weather"

    @property
    def display_name(self) -> str:
        return "Weather (OpenMeteo)"

    async def test_connection(self, config: dict) -> str:
        return "Weather connector - to be implemented in Phase 6"

    async def fetch(self, config: dict) -> list[dict]:
        return []

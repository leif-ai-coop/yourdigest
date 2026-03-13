from app.connectors.base import BaseConnector


class RssConnector(BaseConnector):
    @property
    def connector_type(self) -> str:
        return "rss"

    @property
    def display_name(self) -> str:
        return "RSS Feed"

    async def test_connection(self, config: dict) -> str:
        return "RSS connector - to be implemented in Phase 6"

    async def fetch(self, config: dict) -> list[dict]:
        return []

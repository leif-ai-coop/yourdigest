import httpx
import feedparser
from app.connectors.base import BaseConnector
from app.utils.ssrf import safe_get, SsrfError


class RssConnector(BaseConnector):
    @property
    def connector_type(self) -> str:
        return "rss"

    @property
    def display_name(self) -> str:
        return "RSS Feed"

    async def test_connection(self, config: dict) -> str:
        url = config.get("url")
        if not url:
            return "Error: No URL provided"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await safe_get(client, url)
                resp.raise_for_status()
            parsed = feedparser.parse(resp.text)
            title = parsed.feed.get("title", "Unknown")
            count = len(parsed.entries)
            return f"OK: '{title}' — {count} entries found"
        except SsrfError as e:
            return f"Error: blocked URL ({e})"
        except Exception as e:
            return f"Error: {e}"

    async def fetch(self, config: dict) -> list[dict]:
        return []

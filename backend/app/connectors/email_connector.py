from app.connectors.base import BaseConnector


class EmailConnector(BaseConnector):
    @property
    def connector_type(self) -> str:
        return "email"

    @property
    def display_name(self) -> str:
        return "E-Mail (IMAP/SMTP)"

    async def test_connection(self, config: dict) -> str:
        from app.services.imap_client import test_imap_connection
        return await test_imap_connection(
            host=config["imap_host"],
            port=config.get("imap_port", 993),
            username=config["username"],
            password=config["password"],
            use_ssl=config.get("use_ssl", True),
        )

    async def fetch(self, config: dict) -> list[dict]:
        from app.services.imap_client import fetch_new_messages
        messages = fetch_new_messages(
            host=config["imap_host"],
            port=config.get("imap_port", 993),
            username=config["username"],
            password=config["password"],
            use_ssl=config.get("use_ssl", True),
            last_uid=config.get("last_uid", 0),
        )
        return [msg for _, msg in messages]

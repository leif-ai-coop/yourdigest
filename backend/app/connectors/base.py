from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Base class for all data source connectors."""

    @property
    @abstractmethod
    def connector_type(self) -> str:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @abstractmethod
    async def test_connection(self, config: dict) -> str:
        ...

    @abstractmethod
    async def fetch(self, config: dict) -> list[dict]:
        ...

from app.connectors.base import BaseConnector

_registry: dict[str, BaseConnector] = {}


def register_connector(connector: BaseConnector):
    _registry[connector.connector_type] = connector


def get_connector(connector_type: str) -> BaseConnector | None:
    return _registry.get(connector_type)


def list_connectors() -> list[BaseConnector]:
    return list(_registry.values())

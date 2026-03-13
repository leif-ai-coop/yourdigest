import json
from cryptography.fernet import Fernet
from app.config import get_settings

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        settings = get_settings()
        # Derive a Fernet key from the SECRET_KEY (first 32 bytes, base64 encoded)
        import base64
        import hashlib
        key_bytes = hashlib.sha256(settings.secret_key.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
    return _fernet


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()


def encrypt_config(config: dict) -> str:
    return encrypt_value(json.dumps(config))


def decrypt_config(encrypted: str) -> dict:
    return json.loads(decrypt_value(encrypted))

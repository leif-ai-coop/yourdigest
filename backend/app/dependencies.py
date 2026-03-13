from fastapi import Request, HTTPException
from app.database import get_db  # noqa: F401 - re-export


def get_current_user(request: Request) -> dict:
    """Extract user info from Authentik forward-auth headers."""
    user = request.headers.get("X-authentik-username")
    email = request.headers.get("X-authentik-email")
    name = request.headers.get("X-authentik-name")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": user, "email": email, "name": name}

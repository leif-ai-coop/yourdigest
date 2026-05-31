from fastapi import Request, HTTPException
from app.database import get_db  # noqa: F401 - re-export


def get_current_user(request: Request) -> dict:
    """Extract user info from Authentik forward-auth headers.

    NPM injects X-authentik-* on the /api location (see proxy_host 7.conf).
    We accept username OR uid OR email as proof of a valid forward-auth
    identity — a single missing header must not lock the app out.
    """
    user = request.headers.get("X-authentik-username")
    email = request.headers.get("X-authentik-email")
    name = request.headers.get("X-authentik-name")
    uid = request.headers.get("X-authentik-uid")
    if not (user or uid or email):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": user or uid, "email": email, "name": name, "uid": uid}

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings
from app.dependencies import get_current_user
from app.api import health, connectors, audit, mail, classification, forwarding, digest, feeds, weather, llm, assistant, settings as settings_api, garmin, podcasts, depot, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)

    # Fail fast on a weak/unset SECRET_KEY: the Fernet key for all stored
    # credentials (mail/garmin/LLM) is derived from it.
    if settings.secret_key in {"", "changeme", "dev-secret-key-change-in-production"} or len(settings.secret_key) < 32:
        raise RuntimeError(
            "SECRET_KEY is unset, default, or too short (<32 chars). "
            "Set a strong ASSISTANT_SECRET_KEY before starting."
        )

    logger.info("Assistant API starting up")

    # Seed default podcast prompts
    from app.services.podcast_seed import seed_default_prompts
    await seed_default_prompts()

    if settings.worker_enabled:
        from app.worker.scheduler import start_scheduler, stop_scheduler
        await start_scheduler()

    yield

    if settings.worker_enabled:
        from app.worker.scheduler import stop_scheduler
        await stop_scheduler()

    logger.info("Assistant API shutting down")


app = FastAPI(title="You Digest", version="0.1.0", lifespan=lifespan)

# Rate Limiting
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again later."})

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# health is intentionally unauthenticated (Docker healthcheck hits it via curl
# without Authentik headers). Every other router requires a valid forward-auth
# identity — defense in depth in case the reverse proxy is ever bypassed.
# NPM injects X-authentik-* on the /api location (proxy_host 7.conf).
auth = [Depends(get_current_user)]

app.include_router(health.router)
app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"], dependencies=auth)
app.include_router(audit.router, prefix="/api/audit", tags=["audit"], dependencies=auth)
app.include_router(mail.router, prefix="/api/mail", tags=["mail"], dependencies=auth)
app.include_router(classification.router, prefix="/api/classification", tags=["classification"], dependencies=auth)
app.include_router(forwarding.router, prefix="/api/forwarding", tags=["forwarding"], dependencies=auth)
app.include_router(digest.router, prefix="/api/digest", tags=["digest"], dependencies=auth)
app.include_router(feeds.router, prefix="/api/feeds", tags=["feeds"], dependencies=auth)
app.include_router(weather.router, prefix="/api/weather", tags=["weather"], dependencies=auth)
app.include_router(llm.router, prefix="/api/llm", tags=["llm"], dependencies=auth)
app.include_router(assistant.router, prefix="/api/assistant", tags=["assistant"], dependencies=auth)
app.include_router(settings_api.router, prefix="/api/settings", tags=["settings"], dependencies=auth)
app.include_router(garmin.router, prefix="/api/garmin", tags=["garmin"], dependencies=auth)
app.include_router(podcasts.router, prefix="/api/podcasts", tags=["podcasts"], dependencies=auth)
app.include_router(depot.router, prefix="/api/depot", tags=["depot"], dependencies=auth)
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"], dependencies=auth)

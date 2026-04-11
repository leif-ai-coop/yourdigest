import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings
from app.api import health, connectors, audit, mail, classification, forwarding, digest, feeds, weather, llm, assistant, settings as settings_api, garmin, podcasts


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper()))
    logger = logging.getLogger(__name__)
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

app.include_router(health.router)
app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"])
app.include_router(audit.router, prefix="/api/audit", tags=["audit"])
app.include_router(mail.router, prefix="/api/mail", tags=["mail"])
app.include_router(classification.router, prefix="/api/classification", tags=["classification"])
app.include_router(forwarding.router, prefix="/api/forwarding", tags=["forwarding"])
app.include_router(digest.router, prefix="/api/digest", tags=["digest"])
app.include_router(feeds.router, prefix="/api/feeds", tags=["feeds"])
app.include_router(weather.router, prefix="/api/weather", tags=["weather"])
app.include_router(llm.router, prefix="/api/llm", tags=["llm"])
app.include_router(assistant.router, prefix="/api/assistant", tags=["assistant"])
app.include_router(settings_api.router, prefix="/api/settings", tags=["settings"])
app.include_router(garmin.router, prefix="/api/garmin", tags=["garmin"])
app.include_router(podcasts.router, prefix="/api/podcasts", tags=["podcasts"])

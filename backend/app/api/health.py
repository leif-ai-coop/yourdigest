from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/health")
async def api_health():
    return {"status": "ok", "service": "assistant-api"}

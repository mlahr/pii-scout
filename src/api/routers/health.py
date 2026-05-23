from fastapi import APIRouter, Response

from api.config import settings
from api.schemas import HealthResponse, ReadyResponse, InfoResponse, EntityType

router = APIRouter()

# Will be set by main.py
pii_service = None


def set_pii_service(service):
    global pii_service
    pii_service = service


@router.get("/health", response_model=HealthResponse)
async def health():
    """Liveness probe - returns healthy if server is running."""
    return HealthResponse(status="healthy")


@router.get("/ready", response_model=ReadyResponse)
async def ready(response: Response):
    """Readiness probe - returns ready if model is loaded."""
    if pii_service and pii_service.is_ready:
        return ReadyResponse(
            status="ready",
            model_loaded=True,
            model_profile=settings.model_profile
        )
    response.status_code = 503
    return ReadyResponse(
        status="not_ready",
        model_loaded=False,
        model_profile=None
    )


@router.get("/info", response_model=InfoResponse)
async def info():
    """API metadata and capabilities."""
    model_profile = settings.model_profile
    if pii_service:
        model_profile = pii_service.model_profile

    return InfoResponse(
        version=settings.api_version,
        model_profile=model_profile,
        entity_types=[e.value for e in EntityType],
        max_text_length=settings.max_text_length
    )

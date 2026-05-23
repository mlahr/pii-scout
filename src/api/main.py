import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.config import settings
from api.services.pii_service import PIIService
from api.routers import health, detect
from config.config_loader import load_config, setup_logging


# Configure logging from pii_config.yaml (PII_LOG_LEVEL env var overrides)
config = load_config()
setup_logging(config)
logger = logging.getLogger(__name__)

# Reduce noise from third-party libraries
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("spacy").setLevel(logging.WARNING)

# Global PII service instance
pii_service: PIIService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - load model at startup."""
    global pii_service

    logger.info("Starting PII Detection API...")
    pii_service = PIIService(
        model_profile=settings.model_profile,
        use_gpu=settings.use_gpu,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_base_url=settings.openrouter_base_url,
        openrouter_model=settings.openrouter_model,
        piiranha_model_path=settings.piiranha_model_path
    )
    pii_service.load()

    # Share service with routers
    health.set_pii_service(pii_service)
    detect.set_pii_service(pii_service)

    logger.info("API ready to serve requests")
    yield

    logger.info("Shutting down PII Detection API...")
    pii_service = None
    logger.info("Shutdown complete")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.debug(
            f"{request.method} {request.url.path} "
            f"status={response.status_code} duration={duration_ms:.1f}ms"
        )
        return response


# Create FastAPI app
app = FastAPI(
    title="PII Detection API",
    description="Detect personally identifiable information in text",
    version=settings.api_version,
    lifespan=lifespan
)

# Add middleware
app.add_middleware(RequestLoggingMiddleware)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(detect.router, tags=["detection"])


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False
    )

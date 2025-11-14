"""
Author: Xin Hu | Xenith Technologies LLC
Main application module for IoT Stream Engine.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Dict, List

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.endpoints import telemetry
from app.core.audit import setup_audit_logging
from app.core.auth import require_read_permission
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import init_rate_limiter, rate_limit_middleware
from app.db.session import get_db
from app.services.iot_service import IoTService

# Configure logging
setup_logging()
setup_audit_logging()  # Setup audit logging
logger = logging.getLogger(__name__)

# Prometheus metrics (only HTTP request metrics here, others are in telemetry.py)
http_requests_total = Counter(
    "http_requests_total", "Total number of HTTP requests", ["method", "endpoint"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "Duration of HTTP requests"
)
app_version = Gauge("app_version", "Application version", ["version"])

# Set initial values
app_version.labels(version="1.0.0").set(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    try:
        # Initialize rate limiter with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await init_rate_limiter(settings.REDIS_URL)
                logger.info("Services initialized")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Failed to initialize rate limiter after {max_retries} attempts: {e}"
                    )
                    raise
                logger.warning(
                    f"Rate limiter initialization attempt {attempt + 1} failed: {e}"
                )
                await asyncio.sleep(1)  # Wait before retry
        yield
    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        raise
    finally:
        logger.info("Application shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="IoT Stream Engine API - High-Throughput Sensor Ingestion",
    version="1.0.0",
    lifespan=lifespan,
    debug=settings.DEBUG,
)

# Add security middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],  # In production, specify actual allowed hosts
)

# Add CORS middleware with dynamic settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    max_age=3600,
)

# Include routers
app.include_router(telemetry.router, prefix=settings.API_V1_STR + "/telemetry", tags=["telemetry"])
app.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])


@app.get("/")
async def root() -> Dict[str, str]:
    """
    Root endpoint.

    Returns:
        Welcome message
    """
    return {"message": f"Welcome to the {settings.PROJECT_NAME} API"}


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """
    Health check endpoint.

    Returns:
        Health status
    """
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check() -> Dict[str, str]:
    """
    Readiness check endpoint.

    Checks if the application is ready to serve traffic.
    This includes database connectivity and service dependencies.

    Returns:
        Readiness status
    """
    try:
        # Check database connectivity
        db = next(get_db())
        db.execute(text("SELECT 1"))
        db.close()

        return {"status": "ready", "service": settings.PROJECT_NAME}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")


@app.get("/metrics")
async def metrics() -> Response:
    """
    Prometheus metrics endpoint.

    Returns:
        Application metrics in Prometheus format
    """
    if not settings.PROMETHEUS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics endpoint disabled")
    
    # Return metrics in Prometheus format
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/devices")
async def get_devices(
    db: Session = Depends(get_db), current_user: str = Depends(require_read_permission)
) -> List[str]:
    """
    Get all available devices.

    Args:
        db: Database session
        current_user: Authenticated user

    Returns:
        List of available device IDs
    """
    try:
        devices = IoTService.get_all_devices(db)
        return devices
    except Exception as e:
        logger.error(f"Error getting devices: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error retrieving devices",
        )


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """Middleware to track HTTP requests for Prometheus metrics."""
    start_time = time.time()

    # Track request
    http_requests_total.labels(method=request.method, endpoint=request.url.path).inc()

    response = await call_next(request)

    # Track duration
    duration = time.time() - start_time
    http_request_duration_seconds.observe(duration)

    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Content-Security-Policy"] = "default-src 'self'"

    return response


@app.middleware("http")
async def rate_limit_middleware_wrapper(request: Request, call_next):
    """Rate limiting middleware wrapper."""
    try:
        # Apply rate limiting to all endpoints except health checks
        if not request.url.path.startswith(("/health", "/ready", "/metrics")):
            await rate_limit_middleware(request, max_requests=100, window_seconds=60)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate limiting error: {e}")
        # Continue on error (fail open)

    return await call_next(request)




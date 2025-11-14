"""API package for the IoT Stream Engine."""

from fastapi import APIRouter

from app.api.endpoints import telemetry

api_router = APIRouter()
api_router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])

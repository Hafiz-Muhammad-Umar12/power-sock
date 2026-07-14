"""
REST API endpoints.
Phase 1: health + stubs. Full implementation in Phase 4.
"""

from fastapi import APIRouter

from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse()

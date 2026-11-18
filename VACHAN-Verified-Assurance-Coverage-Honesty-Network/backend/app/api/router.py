"""
Central API router registering all sub-routers under /api/v1.
"""

from fastapi import APIRouter
from app.api.routes import (
    auth,
    claims,
    demo,
    health,
    integrity,
    policies,
    registrations,
    sales_sessions,
    verification,
    voice,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(policies.router)
api_router.include_router(registrations.router)
api_router.include_router(claims.router)
api_router.include_router(sales_sessions.router)
api_router.include_router(verification.router)
api_router.include_router(integrity.router)
api_router.include_router(demo.router)
api_router.include_router(voice.router)

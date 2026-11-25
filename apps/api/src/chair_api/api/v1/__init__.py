"""Version 1 REST API routers."""

from fastapi import APIRouter

from chair_api.api.v1.admin import router as admin_router
from chair_api.api.v1.assets import router as assets_router
from chair_api.api.v1.auth import router as auth_router
from chair_api.api.v1.bookings import router as bookings_router
from chair_api.api.v1.discovery import router as discovery_router
from chair_api.api.v1.health import router as health_router
from chair_api.api.v1.partner import router as partner_router
from chair_api.api.v1.payments import router as payments_router
from chair_api.api.v1.users import router as users_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["health"])
api_v1_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(users_router, prefix="/users", tags=["users"])
api_v1_router.include_router(discovery_router, prefix="/branches", tags=["discovery"])
api_v1_router.include_router(bookings_router, tags=["bookings"])
api_v1_router.include_router(payments_router, prefix="/payments", tags=["payments"])
api_v1_router.include_router(assets_router, prefix="/assets", tags=["assets"])
api_v1_router.include_router(partner_router, prefix="/partner", tags=["partner"])
api_v1_router.include_router(admin_router, prefix="/admin", tags=["admin"])

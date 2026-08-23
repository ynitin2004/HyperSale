from fastapi import APIRouter

from app.modules.identity.api import router as identity_router
from app.modules.platform.api import router as platform_router
from app.modules.practice.api import router as practice_router

api_router = APIRouter()
api_router.include_router(platform_router, tags=["platform"])
api_router.include_router(identity_router, tags=["identity"])
api_router.include_router(practice_router, prefix="/practice", tags=["practice"])

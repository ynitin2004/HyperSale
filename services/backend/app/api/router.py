from fastapi import APIRouter

from app.modules.practice.api import router as practice_router
from app.modules.platform.api import router as platform_router

api_router = APIRouter()
api_router.include_router(platform_router, tags=["platform"])
api_router.include_router(practice_router, prefix="/practice", tags=["practice"])


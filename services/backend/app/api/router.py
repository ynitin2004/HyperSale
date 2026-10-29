from fastapi import APIRouter

from app.modules.catalog.api import router as catalog_router
from app.modules.coaching.api import router as coaching_router
from app.modules.evals.api import router as evals_router
from app.modules.identity.api import router as identity_router
from app.modules.insights.api import router as insights_router
from app.modules.platform.api import router as platform_router
from app.modules.practice.api import router as practice_router
from app.modules.scoring.api import router as scoring_router

api_router = APIRouter()
api_router.include_router(platform_router, tags=["platform"])
api_router.include_router(identity_router, tags=["identity"])
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
api_router.include_router(practice_router, prefix="/practice", tags=["practice"])
api_router.include_router(scoring_router, tags=["scoring"])
api_router.include_router(insights_router, tags=["insights"])
api_router.include_router(coaching_router, tags=["coaching"])
api_router.include_router(evals_router, tags=["evals"])

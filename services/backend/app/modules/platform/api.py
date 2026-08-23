from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings

router = APIRouter()


@router.get("/config")
async def public_config(request: Request) -> dict[str, str]:
    """Safe browser configuration; provider credentials are never returned."""
    return {"environment": get_settings().app_env, "request_id": request.state.request_id}


@router.get("/me")
async def current_user() -> None:
    raise HTTPException(status_code=501, detail="JWT validation is configured during Supabase M0 setup")


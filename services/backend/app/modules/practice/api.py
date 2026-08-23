import hashlib

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()


class RealtimeSessionRequest(BaseModel):
    user_id: str


@router.post("/realtime/session")
async def create_realtime_session(payload: RealtimeSessionRequest) -> dict:
    """Mint a short-lived browser credential; standard provider keys never leave the server."""
    settings = get_settings()
    if not settings.openai_api_key or not settings.openai_safety_identifier_salt:
        raise HTTPException(status_code=503, detail="Realtime provider is not configured")

    safety_id = hashlib.sha256(
        f"{settings.openai_safety_identifier_salt}:{payload.user_id}".encode()
    ).hexdigest()
    body = {
        "session": {
            "type": "realtime",
            "model": settings.openai_realtime_model,
        }
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            json=body,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "OpenAI-Safety-Identifier": safety_id,
            },
        )
    if response.is_error:
        raise HTTPException(status_code=502, detail="Realtime provider session creation failed")
    return response.json()


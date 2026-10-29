"""Recording storage (D31). The api authorizes the caller against the session first; this
adapter only ever sees a workspace-scoped key and never decides who may read what.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx

from app.config import Settings, get_settings
from app.errors import AppError

STORAGE_TIMEOUT_SECONDS = 30.0


def chunk_key(workspace_id: UUID, session_id: UUID, seq: int) -> str:
    # Workspace first: a key can never be built that crosses tenants by accident.
    return f"{workspace_id}/{session_id}/{seq:05d}.part"


class RecordingStore(Protocol):
    async def put_chunk(self, workspace_id: UUID, session_id: UUID, seq: int, data: bytes) -> None: ...

    async def read_all(self, workspace_id: UUID, session_id: UUID, chunks: int) -> bytes: ...


class LocalRecordingStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    async def put_chunk(self, workspace_id: UUID, session_id: UUID, seq: int, data: bytes) -> None:
        path = self._root / chunk_key(workspace_id, session_id, seq)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def read_all(self, workspace_id: UUID, session_id: UUID, chunks: int) -> bytes:
        parts = []
        for seq in range(chunks):
            path = self._root / chunk_key(workspace_id, session_id, seq)
            if not path.exists():
                break
            parts.append(path.read_bytes())
        return b"".join(parts)


class SupabaseRecordingStore:
    def __init__(self, url: str, secret_key: str, bucket: str) -> None:
        self._base = url.rstrip("/") + "/storage/v1"
        self._headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}
        self._bucket = bucket

    async def put_chunk(self, workspace_id: UUID, session_id: UUID, seq: int, data: bytes) -> None:
        key = chunk_key(workspace_id, session_id, seq)
        async with httpx.AsyncClient(timeout=STORAGE_TIMEOUT_SECONDS) as client:
            r = await client.post(
                f"{self._base}/object/{self._bucket}/{key}",
                content=data,
                headers={**self._headers, "Content-Type": "application/octet-stream",
                         "x-upsert": "true"},
            )
        if r.is_error:
            raise AppError("recording_store_failed", "Recording chunk could not be stored",
                           status_code=502)

    async def read_all(self, workspace_id: UUID, session_id: UUID, chunks: int) -> bytes:
        parts = []
        async with httpx.AsyncClient(timeout=STORAGE_TIMEOUT_SECONDS) as client:
            for seq in range(chunks):
                key = chunk_key(workspace_id, session_id, seq)
                r = await client.get(f"{self._base}/object/authenticated/{self._bucket}/{key}",
                                     headers=self._headers)
                if r.status_code == 404:
                    break
                if r.is_error:
                    raise AppError("recording_store_failed", "Recording could not be read",
                                   status_code=502)
                parts.append(r.content)
        return b"".join(parts)


def build_recording_store(settings: Settings | None = None) -> RecordingStore:
    settings = settings or get_settings()
    if settings.recording_store == "supabase":
        if not (settings.supabase_url and settings.supabase_secret_key):
            raise AppError("recording_store_not_configured",
                           "Set SUPABASE_URL and SUPABASE_SECRET_KEY", status_code=503)
        return SupabaseRecordingStore(settings.supabase_url, settings.supabase_secret_key,
                                      settings.recording_bucket)
    return LocalRecordingStore(settings.recording_dir)

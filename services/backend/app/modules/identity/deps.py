"""FastAPI dependencies that turn a bearer token into a workspace-scoped principal."""
from collections.abc import AsyncIterator, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import identity_session, tenant_session
from app.errors import AuthError
from app.modules.identity.service import Principal, resolve_membership
from app.modules.identity.tokens import TokenClaims, get_verifier

bearer_scheme = HTTPBearer(auto_error=False, description="Supabase access token")


async def current_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TokenClaims:
    if credentials is None or not credentials.credentials:
        raise AuthError("missing_token", "An Authorization: Bearer token is required")
    return await get_verifier().verify(credentials.credentials)


def _parse_workspace_header(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise AuthError("invalid_workspace_header", "X-Workspace-Id must be a UUID") from exc


async def current_principal(
    request: Request,
    claims: Annotated[TokenClaims, Depends(current_claims)],
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> Principal:
    requested = _parse_workspace_header(x_workspace_id)
    async with identity_session(claims.user_id) as session:
        membership = await resolve_membership(session, claims.user_id, requested)
        principal = Principal(
            user_id=claims.user_id,
            workspace_id=membership.workspace_id,
            role=membership.role,
            email=claims.email,
        )
    # Logs and traces inherit the tenant without threading it through every call site.
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require_role(minimum: str) -> Callable[[Principal], Principal]:
    def dependency(principal: CurrentPrincipal) -> Principal:
        principal.require_role(minimum)
        return principal

    return dependency


async def tenant_db(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    """Workspace-pinned session. Route handlers must never open a session themselves."""
    async with tenant_session(principal.workspace_id, principal.user_id) as session:
        yield session


TenantSession = Annotated[AsyncSession, Depends(tenant_db)]

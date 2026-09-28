"""WHOOP upstream credentials remain behind MCP-issued audience-bound tokens."""

import asyncio

import httpx
from fastmcp.server.auth import AccessToken, OAuthProxy, TokenVerifier

from .api import BASE, SCOPES


class WhoopVerifier(TokenVerifier):
    def __init__(self, client: httpx.AsyncClient):
        super().__init__(
            required_scopes=[scope for scope in SCOPES if scope != "offline"]
        )
        self.client = client

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            response = await self.client.get(
                f"{BASE}/user/profile/basic",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 200:
                return None
            profile = response.json()
            if not isinstance(profile, dict):
                return None
            user_id = profile.get("user_id")
            if not isinstance(user_id, int) or isinstance(user_id, bool):
                return None
        except (httpx.HTTPError, ValueError):
            return None
        # Only used inside OAuthProxy, never as a standalone token verifier.
        # WHOOP has no introspection endpoint. Each data read enforces its scope upstream.
        return AccessToken(
            token=token, client_id=str(user_id), subject=str(user_id), scopes=SCOPES
        )


class WhoopOAuth(OAuthProxy):
    """Serialize token exchanges with WHOOP's single-use refresh tokens."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.refresh_lock = asyncio.Lock()

    def _prepare_scopes_for_upstream_refresh(self, scopes):
        return ["offline"]

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        # One worker is required; token rotation is not safe across replicas.
        async with self.refresh_lock:
            return await super().exchange_refresh_token(client, refresh_token, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        validated = await super().load_access_token(token)
        if validated is None:
            return None
        # The profile endpoint proves identity, not permission scope. Preserve the
        # MCP grant's scope ceiling; upstream WHOOP enforces actual read scopes.
        granted = set(self.jwt_issuer.verify_token(token).get("scope", "").split())
        return validated.model_copy(
            update={"scopes": [scope for scope in validated.scopes if scope in granted]}
        )

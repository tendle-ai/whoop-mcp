"""Hosted WHOOP connector and its public directory surfaces."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)
from starlette.routing import Mount, Route

from . import api, docs
from .auth import WhoopOAuth, WhoopVerifier
from .diagnostics import OAuthDiagnostics

ASSETS = Path(__file__).resolve().parent / "assets"
if not ASSETS.is_dir():
    ASSETS = Path(__file__).resolve().parents[2] / "assets"


def create_app(
    base: str | None = None, client: httpx.AsyncClient | None = None, auth=None
):
    base = (
        base or os.environ.get("PUBLIC_URL", "https://tendle.ai/connectors/whoop")
    ).rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in ("https", "http")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or not parsed.netloc
    ):
        raise ValueError(
            "PUBLIC_URL must be an HTTP(S) URL without query, fragment, or credentials."
        )
    if parsed.scheme != "https" and parsed.hostname not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise ValueError("PUBLIC_URL must use HTTPS outside localhost.")
    prefix = parsed.path
    owned_client = client is None
    client = client or httpx.AsyncClient(
        timeout=15,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        follow_redirects=False,
    )
    client_id, secret, signing_key = (
        os.environ.get(k)
        for k in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "JWT_SIGNING_KEY")
    )
    if any((client_id, secret, signing_key)) and not all(
        (client_id, secret, signing_key)
    ):
        raise ValueError(
            "Set WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, and JWT_SIGNING_KEY together."
        )
    if auth is None and client_id:
        auth = WhoopOAuth(
            upstream_authorization_endpoint="https://api.prod.whoop.com/oauth/oauth2/auth",
            upstream_token_endpoint="https://api.prod.whoop.com/oauth/oauth2/token",
            upstream_client_id=client_id,
            upstream_client_secret=secret,
            jwt_signing_key=signing_key,
            token_verifier=WhoopVerifier(client),
            base_url=base,
            valid_scopes=api.SCOPES,
            token_endpoint_auth_method="client_secret_post",
            forward_pkce=False,
            forward_resource=False,
            service_documentation_url=base + "/mcp/docs",
        )
    configured = auth is not None
    mcp = FastMCP(
        "WHOOP",
        version="0.1.0",
        auth=auth,
        instructions="Read whoop_get_docs before using WHOOP data. Query fresh data and check pagination and score_state.",
        mask_error_details=True,
        strict_input_validation=True,
    )

    def credential():
        token = get_access_token()
        if token is None:
            raise ToolError(
                "authentication_required: Connect your WHOOP account using OAuth in your MCP client."
            )
        return token.token

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def whoop_get_docs() -> str:
        """Get setup, tool inputs, workflows, units, pagination, errors, and limitations."""
        return await docs.render(mcp, base)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def whoop_get_profile(include_body: bool = False) -> dict:
        """Confirm the connected WHOOP account. Optionally include height, weight, and maximum heart rate."""
        token = credential()
        result = {
            "observed_at": api.now(),
            "profile": await api.read(client, token, "user/profile/basic"),
        }
        if include_body:
            result["body_measurements"] = await api.read(
                client, token, "user/measurement/body"
            )
        return result

    @mcp.tool(annotations={"readOnlyHint": True})
    async def whoop_list_records(
        record_type: api.RecordType,
        start: Annotated[
            str | None,
            Field(
                description="Inclusive timezone-aware ISO 8601 lower bound; omitted means no lower bound."
            ),
        ] = None,
        end: Annotated[
            str | None,
            Field(
                description="Exclusive WHOOP interval upper bound. Defaults to now; reuse returned query.end for pagination."
            ),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=25)] = 25,
        next_token: Annotated[
            str | None,
            Field(
                max_length=4096,
                min_length=1,
                description="Opaque cursor. Reuse original type, bounds, and limit.",
            ),
        ] = None,
        max_pages: Annotated[int, Field(ge=1, le=10)] = 1,
    ) -> dict:
        """Read cycles, recovery, sleep, or workouts, newest first. Returns raw WHOOP records and explicit pagination coverage; no health data is cached."""
        return await api.records(
            client, credential(), record_type, start, end, limit, next_token, max_pages
        )

    @mcp.tool(annotations={"readOnlyHint": True})
    async def whoop_get_record(
        record_type: api.RecordType,
        record_id: Annotated[str, Field(min_length=1, max_length=64)],
    ) -> dict:
        """Read one WHOOP record. cycles/recovery take a cycle ID; sleep/workouts take a v2 UUID from list_records. Missing records are errors, not zero scores."""
        path = api.record_path(record_type, record_id)
        return {
            "observed_at": api.now(),
            "record_type": record_type,
            "record": await api.read(client, credential(), path),
        }

    @mcp.custom_route("/mcp/docs", methods=["GET"])
    async def documentation(request):
        return PlainTextResponse(
            await docs.render(mcp, base), headers={"Cache-Control": "no-store"}
        )

    @mcp.custom_route("/manifest.json", methods=["GET"])
    async def manifest(request):
        return FileResponse(
            ASSETS / "connector.json",
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @mcp.custom_route("/mcp/icon", methods=["GET"])
    async def icon(request):
        return FileResponse(ASSETS / "icon.png", media_type="image/png")

    @mcp.custom_route("/healthz", methods=["GET"])
    async def health(request):
        return JSONResponse(
            {"status": "ok", "oauth_configured": configured, "upstream_verified": False}
        )

    async def product(request):
        return HTMLResponse(
            '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>WHOOP by Tendle</title></head><body><p>Coming soon.</p><a href="'
            + prefix
            + '/manifest.json">Connector metadata</a></body></html>'
        )

    async def unavailable(request):
        return JSONResponse(
            {
                "error": "oauth_not_configured",
                "message": "WHOOP connection setup is pending. Public documentation is available at "
                + base
                + "/mcp/docs.",
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    inner = mcp.http_app(path="/mcp", stateless_http=True, json_response=True)
    if not configured:
        inner.routes.insert(
            0, Route("/mcp", unavailable, methods=["GET", "POST", "DELETE"])
        )
    # RFC 8414 / RFC 9728 metadata lives at the host root even for mounted issuers.
    discovery = [
        r for r in inner.routes if getattr(r, "path", "").startswith("/.well-known/")
    ]
    for route in discovery:
        inner.routes.remove(route)
    if configured:
        discovery = auth.get_well_known_routes("/mcp")

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with inner.lifespan(app):
                yield
        finally:
            if owned_client:
                await client.aclose()

    app = Starlette(
        routes=[
            *discovery,
            Route(prefix or "/", product),
            Mount(prefix or "/", app=inner),
        ],
        lifespan=lifespan,
        middleware=[Middleware(OAuthDiagnostics, prefix=prefix)],
    )
    app.state.mcp = mcp
    return app


def main():
    # Avoid logging HTTP URLs (OAuth codes) or upstream bodies containing health data.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8081")),
        access_log=False,
    )


if __name__ == "__main__":
    main()

import json
import logging

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from whoop_mcp.diagnostics import OAuthDiagnostics

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("status", [201, 400])
async def test_oauth_logs_preserve_response_and_exclude_secrets(caplog, status):
    async def register(request):
        await request.json()
        return JSONResponse(
            {
                "error": "invalid_client_metadata",
                "client_secret": "response-secret",
                "error_description": "private-description",
            },
            status_code=status,
        )

    app = Starlette(
        routes=[Route("/connectors/whoop/register", register, methods=["POST"])],
        middleware=[Middleware(OAuthDiagnostics, prefix="/connectors/whoop")],
    )
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://example.com"
        ) as c:
            r = await c.post(
                "/connectors/whoop/register?code=query-secret",
                headers={
                    "Authorization": "Bearer header-secret",
                    "Cookie": "cookie-secret",
                },
                json={
                    "redirect_uris": [
                        "https://agent.meta.ai/callback-secret?code=uri-secret#fragment-secret"
                    ],
                    "token_endpoint_auth_method": "none",
                    "client_secret": "request-secret",
                },
            )
    assert r.status_code == status and r.json()["client_secret"] == "response-secret"
    event = json.loads(caplog.records[-1].message)
    assert event["request_id"] == r.headers["x-request-id"]
    assert event["redirect_hosts"] == ["agent.meta.ai"]
    assert event.get("error") == ("invalid_client_metadata" if status == 400 else None)
    assert "secret" not in caplog.text and "private-description" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [b"not-json", b"\xff", b"[]", b'{"redirect_uris":["https://["]}', b" " * 20000],
)
async def test_malformed_dcr_logging_never_breaks_response(caplog, body):
    async def register(request):
        await request.body()
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    app = Starlette(
        routes=[Route("/register", register, methods=["POST"])],
        middleware=[Middleware(OAuthDiagnostics, prefix="")],
    )
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://example.com"
        ) as c:
            r = await c.post("/register", content=body)
    assert r.status_code == 400
    assert json.loads(caplog.records[-1].message)["error"] == "invalid_request"

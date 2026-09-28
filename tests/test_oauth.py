import base64
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from key_value.aio.stores.memory import MemoryStore

from whoop_mcp.api import SCOPES
from whoop_mcp.auth import WhoopOAuth, WhoopVerifier
from whoop_mcp.server import create_app

pytestmark = pytest.mark.anyio
BASE = "https://tendle.ai/connectors/whoop"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class UpstreamTokens:
    client_secret = "fake-upstream-secret"
    calls = []

    async def aclose(self):
        pass

    async def fetch_token(self, url, **kwargs):
        self.calls.append(kwargs)
        return {
            "access_token": "whoop-member-access",
            "refresh_token": "whoop-refresh-1",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": " ".join(SCOPES),
        }

    async def refresh_token(self, url, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["scope"] == "offline"
        assert kwargs["refresh_token"] == "whoop-refresh-1"
        return {
            "access_token": "whoop-member-access-new",
            "refresh_token": "whoop-refresh-2",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": " ".join(SCOPES),
        }


async def test_oauth_http_round_trip_and_refresh(monkeypatch):
    async def whoop(request):
        assert request.headers["Authorization"] in (
            "Bearer whoop-member-access",
            "Bearer whoop-member-access-new",
        )
        return httpx.Response(200, json={"user_id": 1234})

    async with httpx.AsyncClient(transport=httpx.MockTransport(whoop)) as provider:
        auth = WhoopOAuth(
            upstream_authorization_endpoint="https://api.prod.whoop.com/oauth/oauth2/auth",
            upstream_token_endpoint="https://api.prod.whoop.com/oauth/oauth2/token",
            upstream_client_id="fake-app",
            upstream_client_secret="fake-upstream-secret",
            jwt_signing_key="test-only-signing-key-never-production",
            token_verifier=WhoopVerifier(provider),
            base_url=BASE,
            client_storage=MemoryStore(),
            forward_pkce=False,
            forward_resource=False,
            valid_scopes=SCOPES,
            token_endpoint_auth_method="client_secret_post",
        )
        monkeypatch.setattr(auth, "_create_upstream_oauth_client", UpstreamTokens)
        app = create_app(client=provider, auth=auth)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://tendle.ai"
            ) as browser:
                metadata = await browser.get(
                    "/.well-known/oauth-authorization-server/connectors/whoop"
                )
                assert metadata.status_code == 200
                assert metadata.json()["issuer"] == BASE
                assert metadata.json()["token_endpoint"] == BASE + "/token"
                resource = await browser.get(
                    "/.well-known/oauth-protected-resource/connectors/whoop/mcp"
                )
                assert resource.status_code == 200
                assert resource.json()["resource"] == BASE + "/mcp"
                registration = await browser.post(
                    BASE + "/register",
                    json={
                        "client_name": "Test MCP client",
                        "redirect_uris": ["https://client.example/callback"],
                        "token_endpoint_auth_method": "none",
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                        "scope": " ".join(SCOPES),
                    },
                )
                assert registration.status_code == 201, registration.text
                registered = registration.json()
                assert "fake-upstream-secret" not in registration.text
                assert registered["client_id"] != "fake-app"
                verifier = "a" * 64
                challenge = (
                    base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                    .rstrip(b"=")
                    .decode()
                )
                response = await browser.get(
                    BASE + "/authorize",
                    params={
                        "client_id": registered["client_id"],
                        "redirect_uri": "https://client.example/callback",
                        "response_type": "code",
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                        "state": "client-state",
                        "scope": " ".join(SCOPES),
                        "resource": BASE + "/mcp",
                    },
                )
                assert response.status_code == 302, response.text
                consent = await browser.get(response.headers["location"])
                assert consent.status_code == 200

                def value(name):
                    return re.search(
                        r'name="' + name + r'"\s+value="([^"]+)"', consent.text
                    ).group(1)

                response = await browser.post(
                    response.headers["location"],
                    data={
                        "txn_id": value("txn_id"),
                        "csrf_token": value("csrf_token"),
                        "action": "approve",
                    },
                )
                assert response.status_code == 302, response.text
                upstream = parse_qs(urlsplit(response.headers["location"]).query)
                assert upstream["redirect_uri"] == [BASE + "/auth/callback"]
                assert "code_challenge" not in upstream
                invalid_state = await browser.get(
                    BASE + "/auth/callback",
                    params={"code": "fake-whoop-code", "state": "unknown-state"},
                )
                assert invalid_state.status_code == 400
                callback = await browser.get(
                    BASE + "/auth/callback",
                    params={"code": "fake-whoop-code", "state": upstream["state"][0]},
                )
                assert callback.status_code == 302, callback.text
                query = parse_qs(urlsplit(callback.headers["location"]).query)
                assert query["state"] == ["client-state"]
                token_request = {
                    "grant_type": "authorization_code",
                    "code": query["code"][0],
                    "code_verifier": verifier,
                    "client_id": registered["client_id"],
                    "redirect_uri": "https://client.example/callback",
                    "resource": BASE + "/mcp",
                }
                wrong_pkce = await browser.post(
                    BASE + "/token",
                    data={**token_request, "code_verifier": "wrong" * 13},
                )
                assert wrong_pkce.status_code in (400, 401)
                token_response = await browser.post(BASE + "/token", data=token_request)
                assert token_response.status_code == 200, token_response.text
                tokens = token_response.json()
                assert "whoop-member-access" not in token_response.text
                assert (
                    await browser.post(BASE + "/token", data=token_request)
                ).status_code in (400, 401)
                assert (await auth.load_access_token("whoop-member-access")) is None
                validated = await auth.load_access_token(tokens["access_token"])
                assert validated.subject == "1234"
                assert validated.token == "whoop-member-access"
                payload = auth.jwt_issuer.verify_token(tokens["access_token"])
                restricted = auth.jwt_issuer.issue_access_token(
                    client_id=registered["client_id"],
                    scopes=["read:profile"],
                    jti=payload["jti"],
                )
                assert (await auth.load_access_token(restricted)).scopes == [
                    "read:profile"
                ]
                expired = auth.jwt_issuer.issue_access_token(
                    client_id=registered["client_id"],
                    scopes=SCOPES,
                    jti=payload["jti"],
                    expires_in=-60,
                )
                assert await auth.load_access_token(expired) is None
                refreshed = await browser.post(
                    BASE + "/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"],
                        "client_id": registered["client_id"],
                    },
                )
                assert refreshed.status_code == 200, refreshed.text
                validated = await auth.load_access_token(
                    refreshed.json()["access_token"]
                )
                assert validated.token == "whoop-member-access-new"
                headers = {
                    "Authorization": "Bearer " + refreshed.json()["access_token"],
                    "Accept": "application/json, text/event-stream",
                }
                result = await browser.post(
                    BASE + "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "whoop_get_profile"},
                    },
                )
                assert result.status_code == 200
                assert (
                    result.json()["result"]["structuredContent"]["profile"]["user_id"]
                    == 1234
                )


@pytest.mark.parametrize(
    "status,payload",
    [
        (401, {}),
        (403, {}),
        (429, {}),
        (500, {}),
        (200, []),
        (200, {}),
        (200, {"user_id": True}),
    ],
)
async def test_verifier_fails_closed(status, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload))
    ) as client:
        assert await WhoopVerifier(client).verify_token("test") is None


async def test_encrypted_persistence(tmp_path, monkeypatch):
    import fastmcp

    monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
    async with httpx.AsyncClient() as client:
        options = dict(
            upstream_authorization_endpoint="https://api.prod.whoop.com/oauth/oauth2/auth",
            upstream_token_endpoint="https://api.prod.whoop.com/oauth/oauth2/token",
            upstream_client_id="test",
            upstream_client_secret="test-client-secret",
            jwt_signing_key="test-only-stable-signing-key",
            token_verifier=WhoopVerifier(client),
            base_url=BASE,
        )
        first = WhoopOAuth(**options)
        await first._client_storage.put(
            "test", {"access_token": "private-test-token"}, collection="test", ttl=100
        )
        assert all(
            b"private-test-token" not in p.read_bytes()
            for p in tmp_path.rglob("*")
            if p.is_file()
        )
        restarted = WhoopOAuth(**options)
        assert (await restarted._client_storage.get("test", collection="test"))[
            "access_token"
        ] == "private-test-token"

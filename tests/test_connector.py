import asyncio

import httpx
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier

from whoop_mcp import api
from whoop_mcp.server import create_app


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestAuth(TokenVerifier):
    __test__ = False

    async def verify_token(self, token):
        if token not in ("alice", "bob"):
            return None
        return AccessToken(token=token, client_id=token, scopes=[])


async def rpc(client, method, params=None, token="alice"):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


@pytest.fixture
async def session():
    requests = []

    async def upstream(request):
        requests.append(request)
        who = request.headers["Authorization"].split()[-1]
        if request.url.path.endswith("profile/basic"):
            return httpx.Response(200, json={"user_id": who, "first_name": who})
        if request.url.path.endswith("measurement/body"):
            return httpx.Response(200, json={"weight_kilogram": 75})
        if request.url.path.endswith("/cycle"):
            return httpx.Response(
                200,
                json={
                    "records": [
                        {
                            "id": 123,
                            "owner": who,
                            "score_state": "PENDING_SCORE",
                            "score": None,
                        }
                    ],
                    "next_token": None,
                },
            )
        return httpx.Response(200, json={"id": "record", "owner": who})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as provider:
        app = create_app(client=provider, auth=TestAuth())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://whoop.tendle.ai",
            ) as client:
                yield client, requests


async def test_protocol_docs_and_public_surfaces(session):
    client, calls = session
    response = await rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "WHOOP"
    tools = (await rpc(client, "tools/list")).json()["result"]["tools"]
    assert len(tools) == 4
    for tool in tools:
        assert tool["annotations"]["readOnlyHint"]
    doc = await client.get("/mcp/docs")
    tool_doc = (await rpc(client, "tools/call", {"name": "whoop_get_docs"})).json()[
        "result"
    ]["content"][0]["text"]
    assert doc.text == tool_doc
    assert "max_pages" in doc.text
    assert not calls
    product = await client.get("/")
    assert 'href="https://whoop.tendle.ai/manifest.json"' in product.text
    for path in ("", "/manifest.json", "/mcp/icon", "/healthz"):
        assert (await client.get(path or "/")).status_code == 200


async def test_auth_isolation_and_read_flow(session):
    client, calls = session
    for token in (None, "garbage"):
        assert (await rpc(client, "tools/list", token=token)).status_code == 401
    for user in ("alice", "bob", "alice"):
        response = await rpc(
            client,
            "tools/call",
            {"name": "whoop_get_profile", "arguments": {"include_body": True}},
            token=user,
        )
        result = response.json()["result"]["structuredContent"]
        assert result["profile"]["user_id"] == user
        assert result["body_measurements"]["weight_kilogram"] == 75
    results = await asyncio.gather(
        *(
            rpc(
                client,
                "tools/call",
                {"name": "whoop_list_records", "arguments": {"record_type": "cycles"}},
                token=user,
            )
            for user in ("alice", "bob")
        )
    )
    for user, response in zip(("alice", "bob"), results):
        data = response.json()["result"]["structuredContent"]
        assert data["records"][0]["owner"] == user
        assert data["records"][0]["score"] is None
        assert data["coverage"] == "complete_for_query"
    for kind, identifier, path in [
        ("cycles", "123", "/cycle/123"),
        ("recovery", "123", "/cycle/123/recovery"),
        ("sleep", "ecfc6a15-4661-442f-a9a4-f160dd7afae8", "/activity/sleep/"),
        ("workouts", "ecfc6a15-4661-442f-a9a4-f160dd7afae8", "/activity/workout/"),
    ]:
        response = await rpc(
            client,
            "tools/call",
            {
                "name": "whoop_get_record",
                "arguments": {"record_type": kind, "record_id": identifier},
            },
        )
        assert not response.json()["result"].get("isError")
        assert path in calls[-1].url.path


@pytest.mark.parametrize(
    "arguments",
    [
        {"record_type": "journal"},
        {"record_type": "cycles", "limit": 0},
        {"record_type": "cycles", "limit": 26},
        {"record_type": "cycles", "limit": True},
        {"record_type": "cycles", "max_pages": 11},
        {"record_type": "cycles", "start": "2026-09-01"},
        {
            "record_type": "cycles",
            "start": "2026-09-02T00:00:00Z",
            "end": "2026-09-01T00:00:00Z",
        },
    ],
)
async def test_invalid_inputs_do_not_reach_whoop(session, arguments):
    client, calls = session
    result = (
        await rpc(
            client, "tools/call", {"name": "whoop_list_records", "arguments": arguments}
        )
    ).json()
    assert result.get("error") or result.get("result", {}).get("isError")
    assert not calls


@pytest.mark.parametrize(
    "kind,value",
    [
        ("cycles", "../user"),
        ("recovery", "0"),
        ("cycles", str(2**63)),
        ("sleep", "123"),
        ("workouts", "foo"),
        ("cycles", "１２３"),
    ],
)
def test_id_validation(kind, value):
    with pytest.raises(ToolError):
        api.record_path(kind, value)


async def test_pagination_and_pinned_window():
    queries = []

    async def upstream(request):
        queries.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "records": [{"id": len(queries)}],
                "next_token": "second" if len(queries) == 1 else None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        data = await api.records(client, "test", "sleep", None, None, 25, None, 2)
        assert data["count"] == 2 and data["coverage"] == "complete_for_query"
        assert queries[0]["end"] == queries[1]["end"]
        assert queries[1]["nextToken"] == "second"
        data = await api.records(
            client, "test", "sleep", None, data["query"]["end"], 25, "second", 1
        )
        assert data["coverage"] == "partial" and not data["has_more"]


async def test_truncated_and_repeated_pages():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"records": [], "next_token": "same"})
        )
    ) as client:
        result = await api.records(client, "test", "cycles", None, None, 25, None, 1)
        assert result["has_more"] and result["coverage"] == "partial"
        with pytest.raises(ToolError, match="repeated"):
            await api.records(client, "test", "cycles", None, None, 25, None, 2)


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "invalid_request"),
        (401, "authorization_expired"),
        (403, "permission_denied"),
        (404, "not_found"),
        (429, "rate_limited"),
        (500, "upstream_unavailable"),
        (302, "upstream_unavailable"),
    ],
)
async def test_safe_errors(status, code):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                status,
                text="sensitive-provider-body",
                headers={"X-RateLimit-Reset": "60"},
            )
        )
    ) as client:
        with pytest.raises(ToolError) as exc:
            await api.read(client, "secret-credential", "cycle")
        assert str(exc.value).startswith(code)
        assert "sensitive" not in str(exc.value) and "secret" not in str(exc.value)


async def test_later_page_error_is_not_success():
    def upstream(request):
        if "nextToken" in request.url.params:
            return httpx.Response(500)
        return httpx.Response(200, json={"records": [{"id": 1}], "next_token": "more"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        with pytest.raises(ToolError, match="upstream_unavailable"):
            await api.records(client, "test", "cycles", None, None, 25, None, 2)


@pytest.mark.parametrize(
    "body", ["not json", "[]", '{"records": null}', '{"records": [], "next_token": 2}']
)
async def test_malformed_provider(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))
    ) as client:
        with pytest.raises(ToolError, match="invalid_upstream_response"):
            await api.records(client, "test", "cycles", None, None, 25, None, 1)


async def test_disabled_configuration(monkeypatch):
    for key in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "JWT_SIGNING_KEY"):
        monkeypatch.delenv(key, raising=False)
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://whoop.tendle.ai"
        ) as client:
            assert (await rpc(client, "tools/list")).status_code == 503
            assert not (await client.get("/healthz")).json()["oauth_configured"]
    monkeypatch.setenv("WHOOP_CLIENT_ID", "incomplete")
    with pytest.raises(ValueError, match="together"):
        create_app()


async def test_network_timeout():
    def timeout(request):
        raise httpx.ReadTimeout("private transport detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ToolError, match="upstream_unavailable"):
            await api.read(client, "secret", "cycle")

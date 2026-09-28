"""Bounded OAuth diagnostics without credentials, query strings or raw payloads."""

import json
import logging
from urllib.parse import urlsplit
from uuid import uuid4

from starlette.types import ASGIApp, Receive, Scope, Send

LOGGER = logging.getLogger("uvicorn.error")
ERRORS = frozenset(
    {
        "invalid_request",
        "invalid_client",
        "invalid_grant",
        "invalid_scope",
        "invalid_redirect_uri",
        "invalid_client_metadata",
        "invalid_token",
        "unauthorized_client",
        "unsupported_grant_type",
        "unsupported_response_type",
        "access_denied",
        "server_error",
        "temporarily_unavailable",
    }
)


class OAuthDiagnostics:
    def __init__(self, app: ASGIApp, prefix: str):
        self.app = app
        self.routes = {
            prefix + "/" + name: name
            for name in (
                "register",
                "authorize",
                "token",
                "consent",
                "auth/callback",
                "mcp",
            )
        }
        self.routes.update(
            {
                "/.well-known/oauth-authorization-server"
                + prefix: "authorization_metadata",
                "/.well-known/oauth-protected-resource"
                + prefix
                + "/mcp": "resource_metadata",
            }
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        stage = self.routes.get(scope.get("path", ""))
        if scope["type"] != "http" or stage is None:
            return await self.app(scope, receive, send)
        trace = uuid4().hex
        status = 500
        request_body, response_body = bytearray(), bytearray()
        request_truncated = False
        response_truncated = False

        async def read():
            nonlocal request_truncated
            message = await receive()
            if stage == "register" and message["type"] == "http.request":
                data = message.get("body", b"")
                request_truncated |= len(request_body) + len(data) > 16384
                request_body.extend(data[: max(0, 16384 - len(request_body))])
            return message

        async def write(message):
            nonlocal status, response_truncated
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", trace.encode()),
                    ],
                }
            if message["type"] == "http.response.body" and status >= 400:
                data = message.get("body", b"")
                response_truncated |= len(response_body) + len(data) > 4096
                response_body.extend(data[: max(0, 4096 - len(response_body))])
            await send(message)

        try:
            await self.app(scope, read, write)
        finally:
            event = {
                "event": "oauth_http",
                "request_id": trace,
                "stage": stage,
                "method": scope["method"],
                "status": status,
            }
            if response_body and not response_truncated:
                try:
                    payload = json.loads(response_body)
                    error = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(error, str) and error in ERRORS:
                        event["error"] = error
                except (ValueError, UnicodeDecodeError):
                    pass
            if request_body and not request_truncated:
                try:
                    payload = json.loads(request_body)
                    if isinstance(payload, dict):
                        redirects = payload.get("redirect_uris")
                        if isinstance(redirects, list):
                            event["redirect_count"] = len(redirects)
                            # Hosts alone identify hosted versus loopback clients; no
                            # usernames, paths, codes, fragments or query parameters.
                            hosts = []
                            for uri in redirects[:5]:
                                if isinstance(uri, str):
                                    host = urlsplit(uri).hostname
                                    if host and len(host) <= 253:
                                        hosts.append(host)
                            event["redirect_hosts"] = hosts
                        method = payload.get("token_endpoint_auth_method")
                        if method in (
                            "none",
                            "client_secret_post",
                            "client_secret_basic",
                        ):
                            event["token_auth_method"] = method
                except (ValueError, UnicodeDecodeError):
                    pass
            LOGGER.info("%s", json.dumps(event, separators=(",", ":")))

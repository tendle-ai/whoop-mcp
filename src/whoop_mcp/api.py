"""WHOOP v2 reads with bounded pagination and no shared user state."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import httpx
from fastmcp.exceptions import ToolError

BASE = "https://api.prod.whoop.com/developer/v2"
RecordType = Literal["cycles", "recovery", "sleep", "workouts"]
PATHS = {
    "cycles": "cycle",
    "recovery": "recovery",
    "sleep": "activity/sleep",
    "workouts": "activity/workout",
}
SCOPES = [
    "read:profile",
    "read:body_measurement",
    "read:cycles",
    "read:recovery",
    "read:sleep",
    "read:workout",
    "offline",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except ValueError:
        raise ToolError(
            "invalid_input: Use an ISO 8601 date-time with a timezone, such as 2026-09-01T00:00:00Z."
        ) from None


async def read(
    client: httpx.AsyncClient, token: str, path: str, params: dict | None = None
) -> dict:
    try:
        response = await client.get(
            f"{BASE}/{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
    except httpx.HTTPError:
        raise ToolError(
            "upstream_unavailable: WHOOP could not be reached. Retry later; no data was returned."
        ) from None
    status = response.status_code
    if status != 200:
        message = {
            400: "invalid_request: WHOOP rejected the query. Check the record ID and time window.",
            401: "authorization_expired: Reconnect your WHOOP account through OAuth.",
            403: "permission_denied: WHOOP denied access. Reconnect with the required read permissions.",
            404: "not_found: No accessible record was found. It may be absent, deleted, or not yet processed.",
        }.get(
            status,
            "upstream_unavailable: WHOOP returned an unexpected response. Retry later.",
        )
        if status == 429:
            delay = response.headers.get(
                "Retry-After", response.headers.get("X-RateLimit-Reset", "")
            )
            wait = (
                f" Wait {delay} seconds." if delay.isdigit() and len(delay) < 10 else ""
            )
            message = f"rate_limited: WHOOP request quota reached.{wait} Retry later; do not repeatedly poll."
        raise ToolError(message)
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except ValueError:
        raise ToolError(
            "invalid_upstream_response: WHOOP did not return a JSON object. Retry later."
        ) from None


async def records(
    client,
    token,
    record_type: RecordType,
    start: str | None,
    end: str | None,
    limit: int,
    next_token: str | None,
    max_pages: int,
) -> dict:
    end = end or now()
    if start and timestamp(start) >= timestamp(end):
        raise ToolError("invalid_input: start must be earlier than end.")
    timestamp(end)
    params = {"end": end, "limit": limit}
    if start:
        params["start"] = start
    if next_token:
        params["nextToken"] = next_token
    results, seen = [], set()
    for page in range(max_pages):
        data = await read(client, token, PATHS[record_type], params)
        items, cursor = data.get("records"), data.get("next_token")
        if (
            not isinstance(items, list)
            or not all(isinstance(item, dict) for item in items)
            or (cursor is not None and not isinstance(cursor, str))
        ):
            raise ToolError(
                "invalid_upstream_response: WHOOP returned an invalid page. No complete result is available."
            )
        results.extend(items)
        if not cursor:
            break
        if cursor in seen or cursor == next_token:
            raise ToolError(
                "invalid_upstream_response: WHOOP repeated a pagination cursor. Restart the query later."
            )
        seen.add(cursor)
        params["nextToken"] = cursor
    return {
        "observed_at": now(),
        "record_type": record_type,
        "query": {"start": start, "end": end, "limit": limit},
        "records": results,
        "count": len(results),
        "pages": page + 1,
        "next_token": cursor or None,
        "has_more": bool(cursor),
        "coverage": "partial" if cursor or next_token else "complete_for_query",
    }


def record_path(record_type: RecordType, record_id: str) -> str:
    if record_type in ("cycles", "recovery"):
        if (
            not record_id.isascii()
            or not record_id.isdecimal()
            or not 0 < int(record_id) < 2**63
        ):
            raise ToolError(
                "invalid_input: cycles and recovery use a positive cycle ID, not a date or sleep ID."
            )
        return f"cycle/{int(record_id)}" + (
            "/recovery" if record_type == "recovery" else ""
        )
    try:
        value = str(UUID(record_id))
    except ValueError:
        raise ToolError(
            "invalid_input: sleep and workouts use v2 UUIDs returned by whoop_list_records."
        ) from None
    return f"{PATHS[record_type]}/{value}"

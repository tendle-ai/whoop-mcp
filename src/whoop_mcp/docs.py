"""The public page and MCP documentation share this source."""

import json

INTRO = """WHOOP MCP connector by Tendle
Full connector catalog: https://tendle.ai

PURPOSE
Read your own WHOOP recovery, physiological cycles, sleep, workouts, profile,
and body measurements through the official v2 API. This is a read-only connector.
It does not change WHOOP records or provide medical diagnosis.

CONNECT
Add {base}/mcp to an MCP client supporting Streamable HTTP and OAuth.
Use the client's built-in or platform-managed connector OAuth setup. Let it
handle discovery, client registration, authorization-code PKCE, secure token
storage, and refresh. No WHOOP developer app credentials are needed from users.
WHOOP returns to {base}/auth/callback; Tendle then returns to the redirect URI
registered by the connecting client. Hosted clients should use their platform's
HTTPS callback. A loopback callback is appropriate only when the client provides
an active listener reachable from the browser in the same network environment.
Do not improvise a local listener for a hosted agent, invent a callback URL, or
replace WHOOP's Tendle callback with the client's callback. If managed OAuth is
unavailable, report the client's missing capability instead of repeatedly signing
in. This connector does not provide device-code or manual connection-key setup.
Authorize Tendle in your browser with WHOOP. Never put passwords or tokens in
prompts, tool inputs, or URLs. All MCP requests require OAuth; this documentation,
the manifest, product page, icon, and health endpoint are public.
One connection represents the WHOOP account authorized in the browser. Run
whoop_get_profile to confirm it, then retrieve a record to verify data access.
A connected label alone does not verify reads. Reconnect to choose another account.
The connector keeps encrypted OAuth credentials to refresh access; it does not
persist health records. Your MCP client receives the health data you request.
Remove Tendle's authorization in WHOOP's connected integrations to revoke access.
Removing a client connection alone may not revoke the upstream grant. Stored
OAuth grants use a 30-day refresh lifetime when WHOOP omits refresh expiry.
Expired encrypted files may remain until operator cleanup; contact
hello@tendle.ai to request deletion.

WORKFLOWS
1. Read whoop_get_profile to confirm account identity. Body measurements are opt-in.
2. Use whoop_list_records with cycles, recovery, sleep, or workouts. Specify a
   timezone-aware start/end window. To find the latest record, omit start and
   use limit=1. Latest means latest returned by WHOOP, not necessarily today.
3. Follow next_token with the SAME record_type, start, end, and limit. The returned
   query.end pins the window when omitted. max_pages fetches several pages in one
   call. has_more=true means more data remains; resumed pages do not include earlier
   records. A later-page failure is an error, never a successful complete report.
4. Fetch details using whoop_get_record. Recovery is addressed by cycle ID;
   sleep and workout records use v2 UUIDs. Join recovery, sleep, and cycle data by
   cycle_id and sleep_id, not by assuming midnight boundaries. Workouts use times.
5. For weekly trends, finish pagination for each relevant type, count scored
   observations, state missing periods, and compare like-for-like intervals.

INTERPRETATION
Always make fresh queries when checking current state. observed_at is retrieval
time, not the time the wearable last synced. WHOOP may revise records later.
Preserve updated_at, timezone_offset, nap, score_state, and calibration flags.
SCORED means a score is available; PENDING_SCORE or UNSCORABLE is not zero.
Missing/null values and absent records are not zero and do not prove no activity.
A physiological cycle is not a calendar day and its end may be null while ongoing.
Naps and main sleeps are distinct. Strain is nonlinear and must not be summed
across workouts as a substitute for cycle strain. Recovery calibration limits
comparability. API queries use WHOOP's documented interval/intersection semantics;
records crossing a boundary may appear in adjacent windows. Deduplicate IDs.
Units stay in WHOOP's original fields: *_milli durations and HRV are milliseconds,
kilojoule is energy (divide by 4.184 for kcal), height_meter is meters,
weight_kilogram is kg, heart rate is bpm, and percentages are percentages.
Use sport_name from current records. Do not guess labels from an old sport list.

ERRORS
invalid_input: correct the ID, bounds, or timezone-aware date-time.
authorization_expired: reconnect using the client's OAuth flow.
permission_denied: reconnect with the required read permissions.
not_found: the record is unavailable; it may be absent, deleted, or unprocessed.
rate_limited: wait for the stated reset; do not repeatedly poll.
upstream_unavailable / invalid_upstream_response: retry later and report the gap.
Do not describe a failed query as an empty account. There are no automatic retries.
WHOOP's default app quota is 100 requests/minute and 10,000/day, shared across
users. OAuth token validation also reads the profile. Prefer bounded date ranges
and pagination over repeated polling. MCP-level authentication may reject a
request before tools run if WHOOP token validation is unavailable.

LIMITATIONS
No journal entries, continuous/raw heart-rate stream, strength-training sets,
workout creation, private mobile APIs, or healthcare partner/lab APIs.
No guaranteed real-time wearable sync or snapshot-consistent historical export.
All data depends on the authorized member's device, permissions, and WHOOP.
New WHOOP developer apps start with a 10-member sandbox cap. Higher tiers require
WHOOP review. Hosting is not WHOOP approval or verified compatibility with every
client. Each client must support the OAuth flow described above.

TOOLS
The input schemas below are generated from the registered tools. Defaults,
allowed values, and bounds are authoritative. All tools are read-only.
"""


async def render(mcp, base: str) -> str:
    sections = [INTRO.format(base=base)]
    for tool in await mcp.list_tools(run_middleware=False):
        sections.append(
            f"{tool.name}\n{tool.description}\nInputs: {json.dumps(tool.parameters, indent=2)}\n"
        )
    return "\n".join(sections)

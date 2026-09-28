# WHOOP MCP

WHOOP MCP connector by Tendle. Check out the full catalog of connectors at https://tendle.ai

A read-only connector for members who want their agent to review recovery, sleep,
strain, and workouts over time. Uses the official WHOOP v2 API and browser OAuth.

- [Product](https://tendle.ai/connectors/whoop)
- [Manifest](https://tendle.ai/connectors/whoop/manifest.json)
- [Plain-text documentation](https://tendle.ai/connectors/whoop/mcp/docs)
- MCP URL: `https://tendle.ai/connectors/whoop/mcp`

**Activation pending:** a WHOOP developer app and consenting member are needed
before hosted personal-data access can be enabled and verified. Public pages and
mocked integration tests are not evidence of a completed live WHOOP connection.

## Tools

| Tool | Purpose |
| --- | --- |
| `whoop_get_docs` | Setup, workflows, generated input schemas, units and limitations |
| `whoop_get_profile` | Confirm account identity; optionally read body measurements |
| `whoop_list_records` | Paginated cycles, recovery, sleep or workouts in a time window |
| `whoop_get_record` | One cycle/recovery by cycle ID, or sleep/workout by v2 UUID |

Get the latest recovery, follow its `sleep_id`, or retrieve complete date windows
for comparisons. There are no redundant daily/weekly wrappers: agents use the same
records and report coverage, missing observations, calibration and score states.
Scores are not medical diagnoses. No journal, strength-training sets, continuous
heart-rate stream, or write operations are exposed by this connector.

## Authentication and privacy

An OAuth-capable MCP client opens the WHOOP sign-in/consent flow. No Tendle account,
manual API token, password, or health data in tool arguments is needed. Confirm the
connected identity with `whoop_get_profile`. Reauthorize to change WHOOP accounts.

FastMCP's OAuth proxy issues audience-bound MCP tokens and keeps upstream tokens
behind encrypted persistent storage. PKCE is enforced between the client and
proxy; upstream WHOOP uses its documented confidential-client authorization-code
flow. Consent remains enabled to bind the requesting client and browser.
Token verification uses WHOOP's profile endpoint. WHOOP enforces each data scope.
Requested read scopes cover all four tools; `offline` enables refresh.

Health records are not persisted or cached by the connector, but your client sees
requested results. OAuth state persists under `FASTMCP_HOME`; protect that directory
and the signing key. The default refresh lifetime is 30 days if WHOOP omits expiry.
Expired encrypted files may remain until operator cleanup.
Revoke Tendle in WHOOP's connected integrations to stop upstream access. Client
removal alone is not upstream revocation. Contact hello@tendle.ai for earlier
server-side credential deletion. WHOOP tokens that are revoked or expire fail closed.

## Run locally

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required.

```sh
uv sync --locked
cp .env.example .env
# Fill the local .env through a secure editor, then:
uv run --env-file .env whoop-mcp
```

Register an app in the [WHOOP developer dashboard](https://developer-dashboard.whoop.com).
Use the exact callback `PUBLIC_URL/auth/callback`, e.g.
`http://localhost:8081/connectors/whoop/auth/callback` locally, or
`https://tendle.ai/connectors/whoop/auth/callback` for the hosted connector.
Enable `read:profile`, `read:body_measurement`, `read:cycles`, `read:recovery`,
`read:sleep`, `read:workout`; request `offline` for refresh.

Set `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, and an independently generated
`JWT_SIGNING_KEY` together. Generate the key locally with
`python -c 'import secrets; print(secrets.token_urlsafe(48))'`.
Keep the key stable across restarts. Never commit `.env` or `.state`.
With all credentials absent, public surfaces run but `/mcp` returns a clear 503
setup-pending error. Partial configuration fails startup. `/healthz` reports
liveness and configuration, not proof that WHOOP is reachable or a grant works.

For self-hosting, use HTTPS, one worker, a private persistent `FASTMCP_HOME`, and a
unique base URL. Route the connector prefix plus its host-root path-aware OAuth
well-known URLs to the application, preserving request paths. Disable access logs
on OAuth callback/token routes. WHOOP refresh tokens rotate; multiple workers or
replicas are unsupported. Use the locked dependencies and protect secret backups.
Update public manifest URLs and activation text for your own deployment.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

## Behavior and limits

Time windows require offsets; pagination pins the end time. A returned page is not
a complete inventory when `has_more` is true. At most ten pages of 25 records are
fetched per call; continue with the cursor and original bounds. Errors on later
pages fail the operation rather than returning a misleading complete report.
WHOOP does not promise snapshot consistency between pages. Use IDs to deduplicate.
Fresh retrieval does not mean the wearable has synced or scoring is finished.

WHOOP's default app quotas are 100 requests/minute and 10,000/day, shared across
members, including profile reads for token validation. New apps support up to ten
members on the Sandbox tier. Higher tiers require WHOOP review. No claim of WHOOP
approval or verified Muse/Grok compatibility is made. Exact client OAuth setup and
live member-data tests remain necessary before launch.

## Verification

40 local tests pass, including an HTTP OAuth simulation through consent, PKCE,
code replay rejection, token refresh, MCP reads, encrypted restart persistence,
user isolation, pagination and upstream failures. Live WHOOP consent and real
member-data reads remain blocked by the missing developer app credentials.

## Research and provenance

Reviewed on 2026-09-28:

- [Official API and schema](https://developer.whoop.com/api/) establish supported v2 reads, pagination, scopes and units.
- [OAuth](https://developer.whoop.com/docs/developing/oauth/) documents confidential-client authorization and rotating refresh tokens.
- [App approval](https://developer.whoop.com/docs/developing/app-approval/) and [rate limits](https://developer.whoop.com/docs/developing/rate-limiting/) constrain rollout and polling.
- [WHOOP community request](https://www.community.whoop.com/t/feature-request-official-whoop-mcp-server-for-llm-use-outside-of-whoop/15329) asks for personal analysis outside WHOOP and cross-source context.
- [Existing official-API connector](https://github.com/jcuw/whoop-mcp) demonstrates read-only personal-agent workflows. This implementation is original, not a source-code fork.
- [Reddit discussion](https://www.reddit.com/r/modelcontextprotocol/comments/1t04z31/i_built_an_unofficial_opensource_whoop_mcp_server/) provides reported use cases, not proof of broad demand.
- [FastMCP OAuth proxy](https://gofastmcp.com/servers/auth/oauth-proxy) supplies the maintained MCP/OAuth protocol implementation; exact dependencies are in `uv.lock`.

These sources support recovery/sleep comparisons, workout review and historical
analysis. Community interest in journal data does not make it available through
the official API. Private mobile APIs and trusted-healthcare-partner endpoints
are deliberately outside this personal connector's scope.

The icon is the official WHOOP Circle Black asset from the
[WHOOP integration asset bundle](https://developer.whoop.com/docs/developing/design-guidelines/),
resized onto a 512x512 PNG canvas. WHOOP branding remains WHOOP's property, subject
to its brand guidelines and terms. The Tendle-authored code is licensed under
Apache-2.0; that license does not grant WHOOP trademark rights or relicense its icon.

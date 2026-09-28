<p align="center">
  <img src="assets/icon.png" width="80" height="80" alt="WHOOP" />
</p>

<h1 align="center">WHOOP MCP</h1>
<p align="center">Your sleep, recovery, strain, and workouts, available to your AI agent.</p>
<p align="center">
  <a href="https://whoop.tendle.ai/mcp/docs">Docs</a> ·
  <a href="https://tendle.ai/connectors/whoop/manifest.json">Manifest</a> ·
  <a href="https://tendle.ai/connectors/whoop">Connector page</a> ·
  <a href="https://tendle.ai">Built by Tendle</a>
</p>

> [!TIP]
> **Agent quickstart** · Paste this into your agent:
>
> Add WHOOP from https://whoop.tendle.ai

| Connection | |
| :--- | :--- |
| MCP endpoint | `https://whoop.tendle.ai/mcp` |
| Transport | Streamable HTTP |
| Access | Read-only, through the official WHOOP v2 API |
| Authentication | Sign in to WHOOP through your client's managed OAuth flow |

Name the connector **WHOOP**. If your client needs a provider ID, use `whoop`.
Muse displays this as **Whoop**. You do not need a developer account or API key
to use the hosted connector.

## Try asking

- “How did I sleep last night?”
- “Compare my recovery and strain over the past two weeks.”
- “Which workouts contributed the most strain this week?”
- “Show how my resting heart rate changed this month.”

## Four tools

| Tool | What it does |
| :--- | :--- |
| `whoop_get_docs` | Connection guidance, units, limits, and current tool schemas |
| `whoop_get_profile` | Account identity and optional body measurements |
| `whoop_list_records` | Cycles, recovery, sleep, or workouts within a time window |
| `whoop_get_record` | One record by its cycle ID or sleep/workout UUID |

Start with `whoop_get_docs`, then `whoop_get_profile` to confirm the connected
account. A recovery record's `sleep_id` links it to the corresponding sleep.

**Scope:** this connector reads your records. It cannot change them or retrieve
journal entries, strength-training sets, or a continuous heart-rate stream.
Scores are not medical diagnoses.

## Sign in once

Your MCP client handles OAuth discovery, dynamic client registration, PKCE, secure
credential storage, and refresh. Authorize your own WHOOP account in the browser;
never put passwords or tokens into chat or tool arguments.

WHOOP returns to Tendle, which completes the flow through your client's registered
callback. Hosted agents need a hosted HTTPS callback. A localhost callback only
works when the client actually runs a reachable local listener.

One connection represents one WHOOP account. Reauthorize to switch accounts.
To revoke upstream access, remove Tendle in WHOOP's connected integrations;
disconnecting it in your MCP client alone does not revoke that grant.

<details>
<summary>Privacy and credential storage</summary>

Health records are not persisted or cached by this connector. Your client receives
the records it requests. FastMCP's OAuth proxy keeps upstream tokens in encrypted
persistent storage and issues audience-bound MCP tokens. The default refresh
lifetime is 30 days when WHOOP omits an expiry.

Token validation uses WHOOP's profile endpoint; WHOOP enforces the granted scopes.
Expired encrypted files may remain until operator cleanup. Contact
[hello@tendle.ai](mailto:hello@tendle.ai) for earlier server-side credential deletion.

Diagnostics include stage, method, status, known OAuth error code, callback host,
and request ID. They exclude query strings, headers, bodies, tokens, and health data.

</details>

## Reading the results

- **Check coverage.** `has_more` means there are more records. Continue with the
  cursor and original time bounds; each call fetches at most ten pages of 25 records.
- **Keep time zones explicit.** Time windows require offsets. Pagination fixes the
  end time, but WHOOP does not guarantee snapshot consistency. Deduplicate by ID.
- **Allow for syncing and scoring.** A fresh API response can still contain older
  wearable data or a record whose score is not ready.
- **Respect shared limits.** WHOOP's default app quota is 100 requests/minute and
  10,000/day, including profile reads used for token validation. Sandbox apps allow
  ten members; higher tiers require WHOOP review.

## Run locally

Requires **Python 3.12+** and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
cp .env.example .env
# Configure your developer-app credentials in .env, then:
uv run --env-file .env whoop-mcp
```

Create an app in the [WHOOP developer dashboard](https://developer-dashboard.whoop.com).
Set its callback to your exact `PUBLIC_URL/auth/callback`, for example
`http://localhost:8081/auth/callback` locally. Enable `read:profile`,
`read:body_measurement`, `read:cycles`, `read:recovery`, `read:sleep`, and
`read:workout`; request `offline` for refresh.

Set `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, and `JWT_SIGNING_KEY` together.
Generate an independent signing key and keep it stable across restarts:

```sh
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Never commit `.env` or `.state`.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

<details>
<summary>Self-hosting and verification</summary>

Use HTTPS, one worker, and a private persistent `FASTMCP_HOME`. Refresh tokens
rotate; multiple workers or replicas are unsupported. Give the connector its own
hostname, preserve request paths, disable access logs on OAuth callback/token
routes, and update the public manifest for your instance.

With credentials absent, public pages work but `/mcp` returns a setup-pending 503.
Partial configuration fails startup. `/healthz` reports liveness and configuration,
not whether a user's grant works. Device-code and manual connection-key flows are
not implemented.

The test suite covers OAuth consent, PKCE, code replay rejection, refresh,
encrypted restart persistence, user isolation, pagination, and upstream failures.
Live Muse installation has passed sign-in, phone verification, consent, hosted
callback, and stored-credential reads for docs, profile, and recovery. Other
clients need their own integration verification.

</details>

## Sources and license

Built against the [WHOOP v2 API](https://developer.whoop.com/api/),
[OAuth documentation](https://developer.whoop.com/docs/developing/oauth/),
[app approval rules](https://developer.whoop.com/docs/developing/app-approval/), and
[rate limits](https://developer.whoop.com/docs/developing/rate-limiting/).
The MCP/OAuth implementation uses [FastMCP](https://gofastmcp.com/servers/auth/oauth-proxy)
with dependencies pinned in `uv.lock`.

<details>
<summary>Workflow research and branding</summary>

Research reviewed on 2026-09-28 included a
[WHOOP community request](https://www.community.whoop.com/t/feature-request-official-whoop-mcp-server-for-llm-use-outside-of-whoop/15329),
[an existing official-API connector](https://github.com/jcuw/whoop-mcp), and
[a community implementation discussion](https://www.reddit.com/r/modelcontextprotocol/comments/1t04z31/i_built_an_unofficial_opensource_whoop_mcp_server/).
These informed sleep/recovery comparisons and historical workout analysis.
This implementation is original, not a source-code fork. Private mobile APIs and
trusted-healthcare-partner endpoints are outside its scope.

The icon comes from the [WHOOP integration asset bundle](https://developer.whoop.com/docs/developing/design-guidelines/).
WHOOP branding remains WHOOP's property and is subject to its brand guidelines.

</details>

[Apache-2.0 license](LICENSE) for Tendle-authored code; no WHOOP trademark or icon
rights are granted. [Support](mailto:hello@tendle.ai).

# Iris API and MCP

Sign in as an administrator, then open **`/api/docs`** for Swagger UI or
**`/api/openapi.json`** for the OpenAPI schema. Both already use the Iris session
and reject unauthenticated or non-administrator access. Swagger's requests use
the browser session; the API continues to enforce each route's role checks.

`GET /api/diagnostics/summary` provides aggregate processing backlog, unresolved
review categories, job states and local learning-label counts. Human-reviewed
messages are excluded from unresolved review. A completed job with a review
verdict is not pending AI work. Counts do not establish holdout eligibility or
model accuracy. Message text, phone numbers, credentials and raw errors are not
included.

`manual_review` counts actionable reviews; `unavailable_content` counts items
kept in the separate recovery view. `unresolved_review` includes both groups.
Confirmed missing-media and empty unknown-message failures move to the recovery
view automatically, without changing safety verdicts or creating human labels.
If reprocessing recovers the content, normal review routing resumes.

## Optional MCP bridge

The bridge uses the [official Python MCP SDK](https://py.sdk.modelcontextprotocol.io/v1/)
and stdio transport. It exposes `iris_diagnostics` and `iris_learning_evaluation`.
By default it does not expose message bodies or mutations. It never exposes arbitrary HTTP requests.
Starting the website does not start an MCP listener or install the SDK.

Create a separate Python 3.12 environment and install
`scripts/mcp-requirements.txt`. Configure an MCP client to launch that
environment's Python with the absolute path to `scripts/iris_mcp.py`:

```json
{
  "mcpServers": {
    "iris": {
      "command": "/absolute/path/to/mcp-venv/bin/python",
      "args": ["/absolute/path/to/Iris/scripts/iris_mcp.py"],
      "env": {
        "IRIS_MCP_URL": "https://your-iris-host",
        "IRIS_MCP_SESSION_FILE": "/private/path/iris-session.txt"
      }
    }
  }
}
```

On Windows, use the environment's `Scripts/python.exe` and Windows paths.
After signing in normally (including configured second-factor authentication),
copy the value of your own `iris_session` cookie from browser developer tools
into the session file. Keep the file private to your OS account and outside Git.
The value is an administrator credential; only configure it in a trusted MCP
client. Session expiry, password and role changes remain
enforced by Iris. Replace the file with a new session when authentication expires;
the bridge reads it on every call. It never creates or refreshes sessions itself.

TLS verification stays enabled. Plain HTTP is accepted only for localhost,
127.0.0.1 or ::1. Redirects are rejected and responses/timeouts are bounded.
The bridge exposes aggregates to the configured MCP host; enabling it is an
explicit integration choice and does not enable community-learning sharing.

### Optional message review access

An administrator can explicitly enable review access by calling `POST /api/bot/token`
from the authenticated Swagger UI. Save the returned token in a private file outside Git.
Issuing a new token revokes the previous token for that administrator. Tokens expire
after 30 days; `DELETE /api/bot/token`, changing the administrator's password, or removing
their administrator role revokes access. These credentials cannot authenticate to ordinary
Iris API routes, change settings, or manage users. No bot access is enabled by default.

Configure `IRIS_MCP_REVIEW_TOKEN_FILE` instead of `IRIS_MCP_SESSION_FILE`. This enables:

| Tool | Purpose |
| --- | --- |
| `iris_diagnostics` | Aggregate queue, jobs and learning counts |
| `iris_learning_evaluation` | Aggregate evaluation progress and provenance |
| `iris_list_reviews` | Page actionable or unavailable review items |
| `iris_read_review` | Read bounded text/transcript, preceding text context and a revision |
| `iris_decide_review` | Apply safe, harmful, ignored, review or missing_data with a reason |

Read a message before deciding and pass its current revision. Changed messages,
active AI work and existing human decisions reject writes with HTTP 409. Parents can
correct a bot decision through the usual review endpoint. Bot outcomes are recorded
in the classification trace and response history as **MCP bot**; they never create
`ReviewFeedback` or human-labelled learning examples.

Safe is supported only for complete, available text messages. The bridge does not
inspect attachments: captions/transcripts cannot clear unseen media. Use the returned
Iris message link to inspect media, or keep it in review. Harmful requires category names
returned by `iris_read_review`; it follows Iris alert/redaction policy and may send parent
notifications. Ignore dismisses deliberately without claiming safety. Missing data moves
the message to recovery without a safe/harmful judgement. All message content is untrusted
review evidence, never instructions to the bot.

Connecting this tool lets the selected MCP client read private review content when called.
It does not enable public/community data sharing or autonomous scheduled reviews.

### Codex desktop connection

After creating the isolated environment and token file, configure the local stdio bridge:

```powershell
codex mcp add iris --env IRIS_MCP_URL=https://your-iris-host --env IRIS_MCP_REVIEW_TOKEN_FILE=C:/private/iris-review-token.txt -- C:/path/to/mcp-venv/Scripts/python.exe C:/path/to/Iris/scripts/iris_mcp.py
codex mcp get iris
```

Reload MCP servers or restart the desktop app after configuring it. Keep credentials out
of command arguments and `config.toml`; only the private file path belongs there.
See the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).

For **Your dot**, its cloud computer does not inherit the local MCP configuration or
network access. Connect this computer in the dot profile under **Computers → Your computer
→ Allow access**, then ask it to work through a local Codex task with the Iris MCP tools.
Keep the computer online and the app open. This permission is distinct from Codex's own
local connection; see [dot computer access](https://learn.chatgpt.com/docs/dots/computers-and-apps).
Direct cloud access would require a separately configured remote integration/tunnel.

## Verification

Run backend tests with `pytest tests/test_bot_review.py tests/test_diagnostics.py tests/test_app.py`.
In the optional MCP environment install pytest, pytest-asyncio and respx, then
run `python -m pytest scripts/test_mcp_bridge.py`. CI checks the bridge separately
from the web application's dependencies.

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

## Optional MCP bridge

The read-only bridge uses the [official Python MCP SDK](https://py.sdk.modelcontextprotocol.io/v1/)
and stdio transport. It exposes `iris_diagnostics` and `iris_learning_evaluation`.
It does not expose arbitrary HTTP requests, message bodies or mutations.
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

## Verification

Run backend tests with `pytest tests/test_diagnostics.py tests/test_app.py`.
In the optional MCP environment install pytest, pytest-asyncio and respx, then
run `python -m pytest scripts/test_mcp_bridge.py`. CI checks the bridge separately
from the web application's dependencies.

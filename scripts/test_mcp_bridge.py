"""Run in the isolated MCP environment: python -m pytest scripts/test_mcp_bridge.py."""

import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.iris_mcp import IrisReader, create_server


@pytest.mark.parametrize(
    "url",
    ["http://remote.test", "https://user:secret@iris.test", "https://iris.test/path", "file:///x"],
)
def test_unsafe_origins_are_rejected(url, tmp_path):
    with pytest.raises(ValueError):
        IrisReader(url, tmp_path / "session")


@pytest.mark.asyncio
@respx.mock
async def test_tools_are_read_only_and_use_fixed_authenticated_routes(tmp_path):
    token = tmp_path / "session"
    token.write_text("test-session")
    server = create_server(IrisReader("https://iris.test", token))
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"iris_diagnostics", "iris_learning_evaluation"}
    assert all(tool.annotations.readOnlyHint for tool in tools)
    route = respx.get("https://iris.test/api/diagnostics/summary").respond(
        200, json={"pending_processing": 0}
    )
    result = await server.call_tool("iris_diagnostics", {})
    assert "pending_processing" in str(result)
    assert route.calls.last.request.headers["cookie"] == "iris_session=test-session"
    # Rotation is picked up on the next call; credentials are never a tool parameter.
    token.write_text("rotated-session")
    await server.call_tool("iris_diagnostics", {})
    assert route.calls.last.request.headers["cookie"] == "iris_session=rotated-session"


@pytest.mark.asyncio
@respx.mock
async def test_no_redirects_or_error_body_disclosure(tmp_path):
    token = tmp_path / "session"
    token.write_text("test-session")
    reader = IrisReader("https://iris.test", token)
    route = respx.get("https://iris.test/api/diagnostics/summary")
    for status in (302, 401, 403, 500):
        route.respond(status, text="private diagnostic", headers={"location": "https://other.test"})
        with pytest.raises(RuntimeError, match=f"HTTP {status}") as exc:
            await reader.read("diagnostics")
        assert "private diagnostic" not in str(exc.value)
    route.mock(side_effect=httpx.ConnectError("private endpoint details"))
    with pytest.raises(RuntimeError, match="Cannot reach Iris"):
        await reader.read("diagnostics")


@pytest.mark.asyncio
@respx.mock
async def test_scoped_review_tools_send_bearer_and_expected_revision(tmp_path):
    token = tmp_path / "review-token"
    token.write_text("scoped-token")
    server = create_server(IrisReader("https://iris.test", token, review_access=True))
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert len(tools) == 5
    assert tools["iris_read_review"].annotations.readOnlyHint
    assert not tools["iris_decide_review"].annotations.readOnlyHint
    route = respx.get("https://iris.test/api/bot/reviews/17").respond(
        200, json={"id": 17, "revision": "a" * 64, "text": "Hello"}
    )
    result = await server.call_tool("iris_read_review", {"message_id": 17})
    assert "Hello" in str(result)
    assert route.calls.last.request.headers["authorization"] == "Bearer scoped-token"
    assert "cookie" not in route.calls.last.request.headers
    write = respx.post("https://iris.test/api/bot/reviews/17").respond(
        200, json={"ok": True, "training_label_created": False}
    )
    await server.call_tool(
        "iris_decide_review",
        {
            "message_id": 17,
            "revision": "a" * 64,
            "action": "safe",
            "reason": "Greeting",
        },
    )
    import json

    assert json.loads(write.calls.last.request.content) == {
        "revision": "a" * 64,
        "action": "safe",
        "reason": "Greeting",
        "categories": [],
    }
    reader = IrisReader("https://iris.test", token, review_access=True)
    with pytest.raises(ValueError):
        await reader.review(-1)
    with pytest.raises(ValueError):
        await reader.reviews(0, 1000, "actionable")


@pytest.mark.asyncio
async def test_real_stdio_protocol_lists_tools_and_enforces_authentication(tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            authorized = self.headers.get("Cookie") == "iris_session=valid-session"
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"pending_processing": 7}).encode())

        def log_message(self, *args):
            pass

    token = tmp_path / "session"
    token.write_text("valid-session")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("iris_mcp.py"))],
        env={
            "IRIS_MCP_URL": f"http://127.0.0.1:{httpd.server_port}",
            "IRIS_MCP_SESSION_FILE": str(token),
        },
    )
    try:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 2
            result = await session.call_tool("iris_diagnostics", {})
            assert not result.isError and "7" in result.content[0].text
            token.write_text("expired-session")
            result = await session.call_tool("iris_diagnostics", {})
            assert result.isError and "401" in result.content[0].text
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)

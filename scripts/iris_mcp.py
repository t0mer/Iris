"""Optional read-only stdio MCP bridge to Iris' authenticated HTTP API."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PATHS = {
    "diagnostics": "/api/diagnostics/summary",
    "learning": "/api/learning/evaluation",
}


class IrisReader:
    def __init__(self, base_url: str, session_file: Path):
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("IRIS_MCP_URL must be an HTTP(S) origin without credentials")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Use HTTPS for non-loopback Iris connections")
        self.base_url = base_url.rstrip("/")
        self.session_file = session_file

    async def read(self, name: str) -> dict:
        path = PATHS[name]  # No arbitrary URL, path, method, or message-content tool.
        token = self.session_file.read_text(encoding="utf-8").strip()
        if not token or any(character.isspace() for character in token):
            raise ValueError("Session file must contain a single Iris session token")
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self.base_url,
                    cookies={"iris_session": token},
                    timeout=15,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream("GET", path) as response,
            ):
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Iris returned HTTP {response.status_code}; check access/session expiry"
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_048_576:
                        raise RuntimeError("Iris response exceeds the bridge limit")
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise RuntimeError("Unexpected Iris response")
                return value
        except httpx.HTTPError:
            raise RuntimeError(
                "Cannot reach Iris; check URL, TLS and service availability"
            ) from None


def create_server(reader: IrisReader):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    server = FastMCP("Iris diagnostics", instructions="Read-only aggregate Iris diagnostics.")
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=annotations)
    async def iris_diagnostics() -> dict:
        """Read processing backlog, review categories, job states and learning label counts."""
        return await reader.read("diagnostics")

    @server.tool(annotations=annotations)
    async def iris_learning_evaluation() -> dict:
        """Read aggregate learning comparisons, progress and model provenance status."""
        return await reader.read("learning")

    return server


if __name__ == "__main__":
    reader = IrisReader(os.environ["IRIS_MCP_URL"], Path(os.environ["IRIS_MCP_SESSION_FILE"]))
    create_server(reader).run(transport="stdio")

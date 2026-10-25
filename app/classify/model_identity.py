"""Resolve installed Ollama model digests without inference or model downloads."""

import httpx

from app.classify.prompt import valid_identity
from app.jobs.queue import TransientError


class ModelIdentityError(TransientError):
    def __init__(self) -> None:
        super().__init__(
            "Ollama model identity is unavailable. Check the provider and retry evaluation."
        )


def canonical_name(name: str) -> str:
    return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"


async def resolve_identity(base_url: str, models: dict[str, str]) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=3, trust_env=False
        ) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            rows = response.json()["models"]
        if not isinstance(rows, list):
            raise ValueError("Invalid model list")
        result = {}
        for role, name in models.items():
            matches = [
                r
                for r in rows
                if isinstance(r, dict)
                and isinstance(r.get("name"), str)
                and canonical_name(r["name"]) == canonical_name(name)
            ]
            if not matches:
                raise ValueError("Missing model")
            digests = {r.get("digest", "").removeprefix("sha256:").lower() for r in matches}
            if len(digests) != 1:
                raise ValueError("Ambiguous model")
            result[role] = digests.pop()
        if not valid_identity(result):
            raise ValueError("Invalid digest")
        return result
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Never persist response bodies, endpoints or authentication details.
        raise ModelIdentityError() from exc

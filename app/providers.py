"""Shared provider clients, rebuilt when the configured credentials change."""

from app.classify.moderation import ModerationClient
from app.classify.ollama import OllamaModerator
from app.config import get_settings


class Providers:
    def __init__(self) -> None:
        self._moderation: tuple[str, ModerationClient] | None = None
        self._retired: list[ModerationClient | OllamaModerator] = []
        self._local: OllamaModerator | None = None
        self._local_config: tuple[str, str, int, int] | None = None

    def moderation(self, api_key: str) -> ModerationClient | OllamaModerator:
        cfg = get_settings()
        if cfg.classification_provider == "ollama":
            selected = (
                cfg.ollama_base_url,
                cfg.ollama_model,
                cfg.ollama_context_tokens,
                cfg.ollama_output_tokens,
            )
            if self._local is None or selected != self._local_config:
                if self._local is not None:
                    self._retired.append(self._local)
                self._local = OllamaModerator(
                    cfg.ollama_base_url,
                    cfg.ollama_model,
                    context_tokens=cfg.ollama_context_tokens,
                    output_tokens=cfg.ollama_output_tokens,
                )
                self._local_config = selected
            return self._local
        if self._moderation is None or self._moderation[0] != api_key:
            if self._moderation is not None:
                self._retired.append(self._moderation[1])
            self._moderation = (api_key, ModerationClient(api_key))
        return self._moderation[1]

    async def aclose(self) -> None:
        if self._local is not None:
            await self._local.aclose()
            self._local = None
        for client in self._retired:
            await client.aclose()
        self._retired = []
        if self._moderation is not None:
            await self._moderation[1].aclose()
            self._moderation = None

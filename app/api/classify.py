"""/api/classify: try the classifier on typed text to tune thresholds. Nothing is kept."""

import time
from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings import ThresholdRow, thresholds
from app.classify.moderation import ModerationClient
from app.classify.ollama import OllamaModerator
from app.classify.stages import build_context_input
from app.classify.thresholds import band_for, effective_thresholds
from app.config import Settings, get_settings
from app.db.models import Message
from app.deps import get_db
from app.jobs.queue import PermanentError, TransientError
from app.security.auth import admin_user
from app.settings_store import get_secret, get_setting

router = APIRouter(prefix="/api/classify", tags=["classify"], dependencies=[Depends(admin_user)])

MAX_CHECKS = 30
WINDOW_SECONDS = 300
# One admin, so one shared window is enough to keep a stuck client from hammering the provider.
_recent: deque[float] = deque()


def _rate_limited(calls: int) -> bool:
    """Each provider call takes a slot, so a check with context costs two."""
    now = time.monotonic()
    while _recent and now - _recent[0] > WINDOW_SECONDS:
        _recent.popleft()
    if len(_recent) + calls > MAX_CHECKS:
        return True
    _recent.extend([now] * calls)
    return False


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    context: list[Annotated[str, Field(max_length=1000)]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def _clean(self) -> "ClassifyRequest":
        self.text = self.text.strip()
        self.context = [t.strip() for t in self.context if t.strip()]
        if not self.text:
            raise ValueError("text must not be blank")
        return self


class StageOut(BaseModel):
    stage: str
    scores: dict[str, float]
    band: str
    high_categories: list[str]
    low_categories: list[str]


class ClassifyResponse(BaseModel):
    model: str
    stages: list[StageOut]
    verdict: str
    thresholds: list[ThresholdRow]


@router.post("/test")
async def classify_test(
    body: ClassifyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    cfg: Annotated[Settings, Depends(get_settings)],
) -> ClassifyResponse:
    key = await get_secret(db, "openai.api_key", cfg.key_bytes)
    if not key and cfg.classification_provider != "ollama":
        raise HTTPException(400, "No OpenAI API key set")
    model = (
        cfg.ollama_model
        if cfg.classification_provider == "ollama"
        else str(await get_setting(db, "classification.model"))
    )
    saved = effective_thresholds(await get_setting(db, "classification.thresholds"))
    inputs = [("moderation", body.text)]
    if body.context:
        previous = [Message(sender_name="Chat", text=t, type="text") for t in body.context]
        target = Message(sender_name="Chat", text=body.text, type="text")
        inputs.append(("context", build_context_input(previous, target)))
    if _rate_limited(len(inputs)):
        raise HTTPException(429, "Too many checks. Wait a few minutes and try again.")
    client = (
        OllamaModerator(cfg.ollama_base_url, cfg.ollama_model)
        if cfg.classification_provider == "ollama"
        else ModerationClient(key or "")
    )
    stages: list[StageOut] = []
    try:
        # With context lines both stages are scored, so the page can re-band either under edited
        # thresholds; the verdict still follows the real pipeline (context only refines "unclear").
        for name, payload in inputs:
            res = await client.moderate(model, payload)
            band, high, low = band_for(res.scores, saved)
            stages.append(
                StageOut(
                    stage=name,
                    scores=res.scores,
                    band=band,
                    high_categories=high,
                    low_categories=low,
                )
            )
    except (PermanentError, TransientError) as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        await client.aclose()
    verdict = stages[0].band
    if verdict == "inconclusive":
        second = stages[1].band if len(stages) > 1 else "inconclusive"
        verdict = "review" if second == "inconclusive" else second
    return ClassifyResponse(
        model=model, stages=stages, verdict=verdict, thresholds=await thresholds(db)
    )

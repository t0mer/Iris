"""Prometheus metrics (spec 13). `/metrics` is unauthenticated: do not expose it publicly."""

import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job

REGISTRY = CollectorRegistry()

WEBHOOKS = Counter(
    "iris_webhooks_total", "Webhook deliveries", ["instance", "result"], registry=REGISTRY
)
MESSAGES = Counter(
    "iris_messages_processed_total", "Classified messages", ["type", "verdict"], registry=REGISTRY
)
STAGE_SECONDS = Histogram(
    "iris_stage_duration_seconds", "Classification stage duration", ["stage"], registry=REGISTRY
)
PROVIDER_REQUESTS = Counter(
    "iris_provider_requests_total",
    "Outbound provider requests",
    ["provider", "endpoint", "status"],
    registry=REGISTRY,
)
PROVIDER_SECONDS = Histogram(
    "iris_provider_duration_seconds",
    "Outbound provider request duration",
    ["provider", "endpoint"],
    registry=REGISTRY,
)
TRANSCRIBED_AUDIO_SECONDS = Counter(
    "iris_transcription_seconds_audio_total",
    "Seconds of audio transcribed",
    ["provider"],
    registry=REGISTRY,
)
ALERTS = Counter(
    "iris_alerts_total",
    "Alerts by top category and delivery outcome",
    ["category", "delivery_status"],
    registry=REGISTRY,
)
MEDIA_STORED = Counter(
    "iris_media_stored_total",
    "Kept media files by backend and result (stored, skipped, failed)",
    ["backend", "result"],
    registry=REGISTRY,
)
JOBS = Gauge("iris_jobs", "Jobs by status", ["status"], registry=REGISTRY)

_JOB_STATUSES = ("queued", "running", "done", "failed", "dead")


def record_provider(provider: str, endpoint: str, status: str, seconds: float) -> None:
    PROVIDER_REQUESTS.labels(provider, endpoint, status).inc()
    PROVIDER_SECONDS.labels(provider, endpoint).observe(seconds)


_GAUGE_TTL = 5.0  # seconds: scrapes inside this window do not touch the database
_gauge_refreshed = 0.0


async def render(db: AsyncSession) -> bytes:
    """Refresh the job gauge from the queue (at most every few seconds), then render."""
    global _gauge_refreshed
    if time.monotonic() - _gauge_refreshed >= _GAUGE_TTL:
        counts = dict(
            (await db.execute(select(Job.status, func.count()).group_by(Job.status))).all()
        )
        for status in _JOB_STATUSES:
            JOBS.labels(status).set(int(counts.get(status, 0)))
        _gauge_refreshed = time.monotonic()
    return generate_latest(REGISTRY)

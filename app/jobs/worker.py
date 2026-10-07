"""Worker pool: N asyncio tasks pulling jobs from the DB queue."""

import asyncio
import shutil
from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.exc import OperationalError

from app.alerts.delivery import deliver_alert, notify_change
from app.chats import resolve_group_names
from app.jobs import queue
from app.jobs.handlers import Deps, process_message
from app.jobs.queue import ClaimedJob, PermanentError, TransientError
from app.media.sweep import sweep_media

Handler = Callable[[ClaimedJob, Deps], Awaitable[None]]
HANDLERS: dict[str, Handler] = {
    "process_message": process_message,
    "deliver_alert": deliver_alert,
    "notify_change": notify_change,
}


async def run_one(job: ClaimedJob, deps: Deps, handlers: dict[str, Handler] = HANDLERS) -> str:
    """Execute a claimed job and record the outcome. Returns the resulting job status."""
    factory = deps.session_factory
    handler = handlers.get(job.type)
    try:
        if handler is None:
            raise PermanentError(f"no handler for job type {job.type!r}")
        await handler(job, deps)
    except TransientError as exc:
        status = await queue.fail(
            factory, job, str(exc), transient=True, retry_after=exc.retry_after
        )
        logger.warning("job {} transient failure ({}): -> {}", job.id, exc, status)
        return status
    except OperationalError as exc:  # e.g. "database is locked": worth retrying
        status = await queue.fail(factory, job, "database busy", transient=True)
        logger.warning("job {} database error ({}): -> {}", job.id, exc.__class__.__name__, status)
        return status
    except PermanentError as exc:
        logger.warning("job {} failed: {}", job.id, exc)
        return await queue.fail(factory, job, str(exc), transient=False)
    except Exception as exc:  # a bug must not kill the worker; never log message content
        logger.exception("job {} crashed", job.id)
        return await queue.fail(
            factory, job, f"unexpected {exc.__class__.__name__}", transient=False
        )
    await queue.ack(factory, job.id)
    return "done"


class WorkerPool:
    def __init__(self, deps: Deps, size: int, poll_interval: float = 1.0) -> None:
        self._deps = deps
        self._size = size
        self._poll = poll_interval
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        # Single process: nothing can be running yet, so any leftover temp media is from a crash.
        await asyncio.to_thread(shutil.rmtree, self._deps.data_dir / "tmp", True)
        recovered = await queue.recover_stale(self._deps.session_factory)
        if recovered:
            logger.info("recovered {} stale jobs", recovered)
        self._tasks = [asyncio.create_task(self._loop(i)) for i in range(self._size)]
        if self._size:
            self._tasks.append(asyncio.create_task(self._maintenance()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    @property
    def alive(self) -> int:
        return sum(1 for t in self._tasks[: self._size] if not t.done())

    @property
    def size(self) -> int:
        return self._size

    async def _maintenance(self) -> None:
        """Housekeeping: re-queue orphaned jobs, and name groups that still have no name."""
        first = True
        while True:
            if not first:
                await asyncio.sleep(60)
            first = False
            try:
                await queue.recover_stale(self._deps.session_factory)
            except Exception:
                logger.exception("stale job recovery failed")
            try:
                await resolve_group_names(self._deps.session_factory, self._deps.key_bytes)
            except Exception:
                logger.exception("group name lookup failed")
            try:
                await sweep_media(
                    self._deps.session_factory, self._deps.key_bytes, self._deps.data_dir
                )
            except Exception:
                logger.exception("media cleanup failed")

    async def _loop(self, n: int) -> None:
        while True:
            try:
                job = await queue.claim(self._deps.session_factory)
                if job is None:
                    await asyncio.sleep(self._poll)
                    continue
                await run_one(job, self._deps)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker {} loop error", n)
                await asyncio.sleep(self._poll)

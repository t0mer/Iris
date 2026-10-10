"""Worker pool: N asyncio tasks pulling jobs from the DB queue."""

import asyncio
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from loguru import logger
from sqlalchemy.exc import OperationalError

from app.alerts.delivery import deliver_alert, deliver_test, notify_change
from app.config import get_settings
from app.jobs import queue
from app.jobs.handlers import Deps, prepare_alert, process_message
from app.jobs.queue import ClaimedJob, PermanentError, TransientError
from app.schedules import due_schedules, run_schedule

Handler = Callable[[ClaimedJob, Deps], Awaitable[None]]
HANDLERS: dict[str, Handler] = {
    "process_message": process_message,
    "prepare_alert": prepare_alert,
    "deliver_alert": deliver_alert,
    "notify_change": notify_change,
    "test_alert": deliver_test,
    "run_schedule": run_schedule,
}


_message_locks: dict[tuple[int, int], tuple[asyncio.Lock, int]] = {}


@asynccontextmanager
async def _message_execution(job: ClaimedJob, deps: Deps) -> AsyncIterator[None]:
    mid = job.payload.get("message_id")
    if job.type != "process_message" or not isinstance(mid, int):
        yield
        return
    key = (id(deps.session_factory), mid)
    lock, users = _message_locks.get(key, (asyncio.Lock(), 0))
    _message_locks[key] = (lock, users + 1)
    try:
        async with lock:
            yield
    finally:
        _, users = _message_locks[key]
        if users == 1:
            del _message_locks[key]
        else:
            _message_locks[key] = (lock, users - 1)


async def run_one(job: ClaimedJob, deps: Deps, handlers: dict[str, Handler] = HANDLERS) -> str:
    interval = get_settings().job_heartbeat_seconds
    if not interval:
        return await _run_one(job, deps, handlers)

    async def renew() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await queue.heartbeat(deps.session_factory, job)
            except Exception:
                logger.warning("job {} heartbeat could not be renewed", job.id)

    lease = asyncio.create_task(renew())
    try:
        return await _run_one(job, deps, handlers)
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)


async def _run_one(job: ClaimedJob, deps: Deps, handlers: dict[str, Handler]) -> str:
    """Execute a claimed job and record the outcome. Returns the resulting job status."""
    factory = deps.session_factory
    handler = handlers.get(job.type)
    try:
        if handler is None:
            raise PermanentError(f"no handler for job type {job.type!r}")
        cfg = get_settings()
        timeout = cfg.job_timeout_seconds
        if not cfg.job_heartbeat_seconds:
            timeout = min(timeout, int(queue.STALE_LOCK.total_seconds()) - 30)
        async with asyncio.timeout(timeout), _message_execution(job, deps):
            async with factory() as db:
                await queue.ensure_owned(db, job)
                await db.commit()
            await handler(job, deps)
    except queue.LostLeaseError:
        return "superseded"
    except TimeoutError:
        return await queue.fail(
            factory,
            job,
            "Handler exceeded its execution time limit",
            transient=job.type in ("process_message", "prepare_alert"),
            uncertain_delivery=job.type in ("deliver_alert", "notify_change", "test_alert"),
        )
    except queue.DeferredError as exc:
        return await queue.defer(factory, job, exc.delay)
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
        logger.error("job {} crashed ({})", job.id, exc.__class__.__name__)
        return await queue.fail(
            factory, job, f"unexpected {exc.__class__.__name__}", transient=False
        )
    await queue.ack(factory, job.id, job.attempts)
    return "done"


class WorkerPool:
    def __init__(self, deps: Deps, size: int, poll_interval: float = 1.0) -> None:
        self._deps = deps
        self._size = size
        self._delivery_size = get_settings().delivery_workers if size else 0
        self._operations_size = 1 if size else 0
        self._poll = poll_interval
        self._tasks: list[asyncio.Task[None]] = []
        self._generation = 0
        self._maintenance_started = False

    async def start(self) -> None:
        # Single process: nothing can be running yet, so any leftover temp media is from a crash.
        await asyncio.to_thread(shutil.rmtree, self._deps.data_dir / "tmp", True)
        recovered = await queue.recover_stale(self._deps.session_factory)
        if recovered:
            logger.info("recovered {} stale jobs", recovered)
        self._tasks = [
            asyncio.create_task(self._loop(i, generation=self._generation))
            for i in range(self._size)
        ]
        self._tasks.extend(
            asyncio.create_task(
                self._loop(self._size + i, delivery=True, generation=self._generation)
            )
            for i in range(self._delivery_size)
        )
        if self._operations_size:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        self._size + self._delivery_size,
                        operations=True,
                        generation=self._generation,
                    )
                )
            )
        if self._size:
            self._tasks.append(asyncio.create_task(self._maintenance()))
            self._maintenance_started = True

    async def reconfigure(self, size: int, delivery_size: int) -> None:
        """New workers use new settings; old in-flight jobs finish without cancellation."""
        delivery_size = delivery_size if size else 0
        if (size, delivery_size) == (self._size, self._delivery_size):
            return
        self._generation += 1
        self._size, self._delivery_size = size, delivery_size
        self._operations_size = 1 if size else 0
        active = [task for task in self._tasks if not task.done()]
        generation = self._generation
        self._tasks = [
            asyncio.create_task(self._loop(i, generation=generation)) for i in range(size)
        ]
        self._tasks.extend(
            asyncio.create_task(self._loop(size + i, delivery=True, generation=generation))
            for i in range(delivery_size)
        )
        if self._operations_size:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(size + delivery_size, operations=True, generation=generation)
                )
            )
        self._tasks.extend(active)
        if size and not self._maintenance_started:
            self._tasks.append(asyncio.create_task(self._maintenance()))
            self._maintenance_started = True

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    @property
    def alive(self) -> int:
        return sum(1 for t in self._tasks[: self.size] if not t.done())

    @property
    def size(self) -> int:
        return self._size + self._delivery_size + self._operations_size

    async def _maintenance(self) -> None:
        """Housekeeping: re-queue orphaned jobs, and name groups that still have no name."""
        first = True
        while True:
            if not first:
                await asyncio.sleep(5)
            first = False
            if self._size:
                try:
                    await due_schedules(self._deps)
                except Exception:
                    logger.exception("Schedule dispatch failed")

    async def _loop(
        self, n: int, delivery: bool = False, operations: bool = False, generation: int = 0
    ) -> None:
        while generation == self._generation:
            try:
                delivery_types = ("deliver_alert", "notify_change", "test_alert")
                job = await queue.claim(
                    self._deps.session_factory,
                    types=("run_schedule",)
                    if operations
                    else (delivery_types if delivery else None),
                    exclude_types=(
                        ()
                        if operations
                        else ("run_schedule",)
                        + (delivery_types if self._delivery_size and not delivery else ())
                    ),
                )
                if job is None:
                    await asyncio.sleep(self._poll)
                    continue
                await run_one(job, self._deps)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker {} loop error", n)
                await asyncio.sleep(self._poll)

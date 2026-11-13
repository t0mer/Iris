"""/api/jobs: failed and dead jobs with their errors, plus manual retry."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.deps import get_db
from app.jobs.queue import retry_job
from app.security.auth import admin_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(admin_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


class JobOut(BaseModel):
    id: int
    type: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    message_id: int | None
    run_after: datetime
    created_at: datetime


@router.get("")
async def list_jobs(db: DB, status: str | None = None, limit: int = 100) -> list[JobOut]:
    """Failed and dead jobs by default (the ones needing attention)."""
    stmt = select(Job).order_by(Job.id.desc()).limit(min(max(limit, 1), 500))
    stmt = (
        stmt.where(Job.status == status)
        if status
        else stmt.where(Job.status.in_(["failed", "dead"]))
    )
    return [
        JobOut(
            id=j.id,
            type=j.type,
            status=j.status,
            attempts=j.attempts,
            max_attempts=j.max_attempts,
            last_error=j.last_error,
            created_at=j.created_at,
            run_after=j.run_after,
            message_id=j.payload.get("message_id")
            if isinstance(j.payload.get("message_id"), int)
            else None,
        )
        for j in (await db.execute(stmt)).scalars()
    ]


@router.post("/{job_id}/retry")
async def retry(job_id: int, db: DB) -> dict[str, bool]:
    if not await retry_job(db, job_id, manual=True):
        raise HTTPException(status_code=409, detail="Only failed or dead jobs can be retried")
    return {"ok": True}

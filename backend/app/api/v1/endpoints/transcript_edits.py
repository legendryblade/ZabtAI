# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api import deps
from app.models import TranscriptEditJob, User
from app.schemas.transcript_edits import (
    TranscriptEditApplyRequest,
    TranscriptEditApplyResponse,
    TranscriptEditCreateRequest,
    TranscriptEditCreateResponse,
    TranscriptEditDiscardRequest,
    TranscriptEditDiscardResponse,
    TranscriptEditGetResponse,
    TranscriptEditProposalRead,
    TranscriptEditRead,
    TranscriptEditScope,
)
from app.services import transcript_edit_jobs as edit_jobs
from app.services.transcript_edit_llm import (
    TranscriptEditLLMError,
    ensure_available,
)


router = APIRouter()


def _raise_http(error: Exception) -> None:
    if isinstance(error, TranscriptEditLLMError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcript edit service is unavailable",
        ) from error
    if isinstance(error, edit_jobs.TranscriptEditError):
        detail = str(error) or error.detail
        raise HTTPException(status_code=error.status_code, detail=detail) from error
    raise error


def _to_response(job: TranscriptEditJob) -> TranscriptEditRead:
    proposal = None
    if job.proposal:
        proposal = TranscriptEditProposalRead.model_validate(job.proposal)
    return TranscriptEditRead(
        id=job.id,
        meeting_id=job.meeting_id,
        requested_by=job.requested_by,
        instruction=job.instruction,
        scope=TranscriptEditScope.model_validate(job.scope),
        base_revision=int(job.base_revision or 0),
        status=str(job.status),
        proposal=proposal,
        error=job.error,
        created_at=job.created_at,
        applied_at=job.applied_at,
    )


@router.post(
    "/{meeting_id}/transcript-edits",
    response_model=TranscriptEditCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_transcript_edit(
    meeting_id: int,
    body: TranscriptEditCreateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> TranscriptEditRead:
    try:
        job = edit_jobs.create_edit_job(db, meeting_id, current_user.id, body)
    except Exception as exc:
        _raise_http(exc)
    try:
        ensure_available()
    except Exception as exc:
        edit_jobs.fail_edit_job(db, job.id, "Transcript edit model is unavailable")
        _raise_http(exc)
    try:
        from app.worker import process_transcript_edit

        process_transcript_edit.delay(job.id)
    except Exception as exc:
        edit_jobs.fail_edit_job(db, job.id, "Transcript edit worker is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcript edit service is unavailable",
        ) from exc
    return _to_response(job)


@router.get(
    "/{meeting_id}/transcript-edits/{edit_id}",
    response_model=TranscriptEditGetResponse,
)
def get_transcript_edit(
    meeting_id: int,
    edit_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> TranscriptEditRead:
    try:
        job = edit_jobs.get_edit_job(db, meeting_id, edit_id, current_user.id)
    except Exception as exc:
        _raise_http(exc)
    return _to_response(job)


@router.post(
    "/{meeting_id}/transcript-edits/{edit_id}/apply",
    response_model=TranscriptEditApplyResponse,
)
def apply_transcript_edit(
    meeting_id: int,
    edit_id: str,
    body: TranscriptEditApplyRequest | None = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> TranscriptEditRead:
    expected_revision = None
    if body is not None:
        expected_revision = (
            body.expected_revision
            if body.expected_revision is not None
            else body.base_revision
        )
    try:
        job = edit_jobs.apply_edit_job(
            db,
            meeting_id,
            edit_id,
            current_user.id,
            expected_revision=expected_revision,
        )
    except Exception as exc:
        _raise_http(exc)
    return _to_response(job)


@router.post(
    "/{meeting_id}/transcript-edits/{edit_id}/discard",
    response_model=TranscriptEditDiscardResponse,
)
def discard_transcript_edit(
    meeting_id: int,
    edit_id: str,
    body: TranscriptEditDiscardRequest | None = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> TranscriptEditRead:
    try:
        job = edit_jobs.discard_edit_job(db, meeting_id, edit_id, current_user.id)
    except Exception as exc:
        _raise_http(exc)
    return _to_response(job)

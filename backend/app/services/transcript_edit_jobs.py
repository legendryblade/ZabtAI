# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.config import settings
from app.db.engine import engine
from app.models import Meeting, MeetingSpeaker, TranscriptEditJob, TranscriptSegment
from app.schemas.transcript_edits import (
    RenameSpeakerOperation,
    ReassignSpeakerOperation,
    ReplaceTextOperation,
    StoredReassignSpeakerOperation,
    StoredRenameSpeakerOperation,
    StoredReplaceTextOperation,
    TranscriptEditCreateRequest,
    TranscriptEditProposal,
    TranscriptEditProposalRead,
    TranscriptEditScope,
)
from app.services.transcript import serialize_transcript
from app.services.transcript_edit_llm import (
    TranscriptEditLLMError,
    generate_transcript_edit_proposal,
)


JOB_QUEUED = "queued"
JOB_PROCESSING = "processing"
JOB_COMPLETED = "completed"
JOB_APPLIED = "applied"
JOB_DISCARDED = "discarded"
JOB_FAILED = "failed"
READY_STATUSES = {JOB_COMPLETED}
ACTIVE_STATUSES = {JOB_QUEUED, JOB_PROCESSING, JOB_COMPLETED}


class TranscriptEditError(Exception):
    status_code = 500
    detail = "Transcript edit request failed"


class TranscriptEditNotFound(TranscriptEditError):
    status_code = 404
    detail = "Transcript edit job not found"


class TranscriptEditConflict(TranscriptEditError):
    status_code = 409
    detail = "Transcript edit is no longer applicable"


class TranscriptEditValidationError(TranscriptEditError):
    status_code = 422
    detail = "Invalid transcript edit"


class TranscriptEditRateLimited(TranscriptEditError):
    status_code = 429
    detail = "Too many transcript edit jobs are already active"


class TranscriptEditUnavailable(TranscriptEditError):
    status_code = 503
    detail = "Transcript edit service is unavailable"


def _safe_error(message: str) -> str:
    return message[:500]


def _speaker_key(segment: TranscriptSegment) -> str:
    return (segment.speaker or "").strip() or "SPEAKER_UNKNOWN"


def _load_segments(session: Session, meeting_id: int) -> list[TranscriptSegment]:
    return list(
        session.exec(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_time, TranscriptSegment.id)
        ).all()
    )


def _load_profiles(session: Session, meeting_id: int) -> list[MeetingSpeaker]:
    return list(
        session.exec(
            select(MeetingSpeaker)
            .where(MeetingSpeaker.meeting_id == meeting_id)
            .order_by(MeetingSpeaker.speaker_key)
        ).all()
    )


def sync_speaker_profiles(
    session: Session,
    meeting_id: int,
    segments: list[TranscriptSegment],
) -> list[MeetingSpeaker]:
    current_keys = {_speaker_key(segment) for segment in segments}
    profiles = _load_profiles(session, meeting_id)
    by_key = {profile.speaker_key: profile for profile in profiles}
    for key, profile in list(by_key.items()):
        if key not in current_keys:
            session.delete(profile)
            del by_key[key]
    for key in sorted(current_keys):
        if key not in by_key:
            profile = MeetingSpeaker(
                meeting_id=meeting_id,
                speaker_key=key,
                display_name=key,
            )
            session.add(profile)
            by_key[key] = profile
    session.flush()
    return list(by_key.values())


def _get_owned_meeting(
    session: Session,
    meeting_id: int,
    user_id: int,
    lock: bool = False,
) -> Meeting:
    statement = select(Meeting).where(Meeting.id == meeting_id)
    if lock:
        statement = statement.with_for_update()
    meeting = session.exec(statement).first()
    if meeting is None or meeting.owner_id != user_id:
        raise TranscriptEditNotFound("Meeting not found")
    return meeting


def _get_owned_job(
    session: Session,
    meeting_id: int,
    edit_id: str,
    user_id: int,
    lock: bool = False,
) -> tuple[Meeting, TranscriptEditJob]:
    meeting = _get_owned_meeting(session, meeting_id, user_id, lock=lock)
    statement = select(TranscriptEditJob).where(
        TranscriptEditJob.id == edit_id,
        TranscriptEditJob.meeting_id == meeting_id,
    )
    if lock:
        statement = statement.with_for_update()
    job = session.exec(statement).first()
    if job is None:
        raise TranscriptEditNotFound("Transcript edit job not found")
    return meeting, job


def _scope_segments(
    scope: TranscriptEditScope,
    segments: list[TranscriptSegment],
    profiles: list[MeetingSpeaker],
) -> list[TranscriptSegment]:
    by_id = {segment.id: segment for segment in segments if segment.id is not None}
    known_keys = {_speaker_key(segment) for segment in segments}
    known_keys.update(profile.speaker_key for profile in profiles)
    if scope.type == "whole_transcript":
        return list(segments)
    if scope.type == "segments":
        selected_ids = set(scope.segment_ids or [])
        if not selected_ids.issubset(by_id):
            missing = sorted(selected_ids - set(by_id))
            raise TranscriptEditValidationError(f"Unknown segment IDs: {missing}")
        return [segment for segment in segments if segment.id in selected_ids]
    selected_keys = set(scope.speaker_keys or [])
    unknown_keys = sorted(selected_keys - known_keys)
    if unknown_keys:
        raise TranscriptEditValidationError(f"Unknown speaker keys: {unknown_keys}")
    return [segment for segment in segments if _speaker_key(segment) in selected_keys]


def _validate_scope_for_meeting(
    session: Session,
    meeting: Meeting,
    scope: TranscriptEditScope,
) -> tuple[list[TranscriptSegment], list[MeetingSpeaker]]:
    segments = _load_segments(session, meeting.id)
    profiles = _load_profiles(session, meeting.id)
    if not segments:
        raise TranscriptEditValidationError("Meeting has no transcript segments")
    _scope_segments(scope, segments, profiles)
    return segments, profiles


def create_edit_job(
    session: Session,
    meeting_id: int,
    user_id: int,
    request: TranscriptEditCreateRequest,
) -> TranscriptEditJob:
    meeting = _get_owned_meeting(session, meeting_id, user_id, lock=True)
    if meeting.status != "completed":
        raise TranscriptEditConflict("Transcript edits require a completed meeting")
    _validate_scope_for_meeting(session, meeting, request.scope)
    active_jobs = session.exec(
        select(TranscriptEditJob).where(
            TranscriptEditJob.meeting_id == meeting_id,
            TranscriptEditJob.status.in_(list(ACTIVE_STATUSES)),
        )
    ).all()
    if len(active_jobs) >= max(0, settings.TRANSCRIPT_EDIT_MAX_ACTIVE_JOBS):
        raise TranscriptEditRateLimited()
    job = TranscriptEditJob(
        meeting_id=meeting_id,
        requested_by=user_id,
        instruction=request.instruction,
        scope=request.scope.model_dump(mode="json", exclude_none=True),
        base_revision=int(meeting.transcript_revision or 0),
        status=JOB_QUEUED,
    )
    session.add(job)
    try:
        session.commit()
        session.refresh(job)
    except Exception:
        session.rollback()
        raise
    return job


def get_edit_job(
    session: Session,
    meeting_id: int,
    edit_id: str,
    user_id: int,
) -> TranscriptEditJob:
    _, job = _get_owned_job(session, meeting_id, edit_id, user_id)
    return job


def _set_failed(
    session: Session,
    job: TranscriptEditJob,
    message: str,
) -> None:
    locked_job = session.exec(
        select(TranscriptEditJob)
        .where(TranscriptEditJob.id == job.id)
        .with_for_update()
    ).first()
    if locked_job is None or locked_job.status in {JOB_APPLIED, JOB_DISCARDED}:
        session.rollback()
        return
    locked_job.status = JOB_FAILED
    locked_job.proposal = None
    locked_job.error = _safe_error(message)
    session.add(locked_job)
    session.commit()


def fail_edit_job(session: Session, edit_id: str, message: str) -> None:
    job = session.get(TranscriptEditJob, edit_id)
    if job is None:
        return
    try:
        _set_failed(session, job, message)
    except Exception:
        session.rollback()


def _proposal_payload(
    segments: list[TranscriptSegment],
    profiles: list[MeetingSpeaker],
    scope: TranscriptEditScope,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    scoped_segments = _scope_segments(scope, segments, profiles)
    segment_payload = [
        {
            "segment_id": segment.id,
            "speaker_key": _speaker_key(segment),
            "text": segment.text,
        }
        for segment in scoped_segments
    ]
    profile_payload = [
        {"speaker_key": profile.speaker_key, "display_name": profile.display_name}
        for profile in profiles
    ]
    return segment_payload, profile_payload


def _build_stored_proposal(
    proposal: TranscriptEditProposal,
    scope: TranscriptEditScope,
    segments: list[TranscriptSegment],
    profiles: list[MeetingSpeaker],
) -> TranscriptEditProposalRead:
    scoped_segments = _scope_segments(scope, segments, profiles)
    allowed_ids = {segment.id for segment in scoped_segments}
    segment_by_id = {segment.id: segment for segment in scoped_segments}
    known_keys = {_speaker_key(segment) for segment in segments}
    known_keys.update(profile.speaker_key for profile in profiles)
    scoped_keys = {_speaker_key(segment) for segment in scoped_segments}
    used_segment_ids: set[int] = set()
    renamed_keys: set[str] = set()
    stored_operations = []
    for operation in proposal.operations:
        if isinstance(operation, ReplaceTextOperation):
            if operation.segment_id not in allowed_ids or operation.segment_id not in segment_by_id:
                raise TranscriptEditValidationError("Proposal references a segment outside its scope")
            if operation.segment_id in used_segment_ids:
                raise TranscriptEditValidationError("A segment can only be changed once")
            segment = segment_by_id[operation.segment_id]
            stored_operations.append(
                StoredReplaceTextOperation(
                    operation=operation.operation,
                    segment_id=operation.segment_id,
                    replacement_text=operation.replacement_text,
                    before={
                        "segment_id": segment.id,
                        "text": segment.text,
                        "speaker": segment.speaker,
                        "start_time": segment.start_time,
                        "end_time": segment.end_time,
                        "words": segment.words or [],
                    },
                )
            )
            used_segment_ids.add(operation.segment_id)
        elif isinstance(operation, RenameSpeakerOperation):
            if operation.speaker_key not in known_keys:
                raise TranscriptEditValidationError("Proposal references an unknown speaker")
            if scope.type == "speakers" and operation.speaker_key not in set(scope.speaker_keys or []):
                raise TranscriptEditValidationError("Proposal renames a speaker outside its scope")
            if scope.type == "segments" and operation.speaker_key not in scoped_keys:
                raise TranscriptEditValidationError("Proposal renames a speaker outside its scope")
            if operation.speaker_key in renamed_keys:
                raise TranscriptEditValidationError("A speaker can only be renamed once")
            profile = next(
                (item for item in profiles if item.speaker_key == operation.speaker_key),
                None,
            )
            stored_operations.append(
                StoredRenameSpeakerOperation(
                    operation=operation.operation,
                    speaker_key=operation.speaker_key,
                    display_name=operation.display_name,
                    before={
                        "speaker_key": operation.speaker_key,
                        "display_name": profile.display_name if profile else operation.speaker_key,
                    },
                )
            )
            renamed_keys.add(operation.speaker_key)
        elif isinstance(operation, ReassignSpeakerOperation):
            if operation.target_speaker_key not in known_keys:
                raise TranscriptEditValidationError("Proposal references an unknown target speaker")
            if any(segment_id not in allowed_ids for segment_id in operation.segment_ids):
                raise TranscriptEditValidationError("Proposal references a segment outside its scope")
            if used_segment_ids.intersection(operation.segment_ids):
                raise TranscriptEditValidationError("A segment can only be changed once")
            before_segments = []
            for segment_id in operation.segment_ids:
                segment = segment_by_id[segment_id]
                before_segments.append(
                    {"segment_id": segment_id, "speaker": segment.speaker}
                )
            stored_operations.append(
                StoredReassignSpeakerOperation(
                    operation=operation.operation,
                    segment_ids=operation.segment_ids,
                    target_speaker_key=operation.target_speaker_key,
                    before={"segments": before_segments},
                )
            )
            used_segment_ids.update(operation.segment_ids)
        else:
            raise TranscriptEditValidationError("Unsupported transcript edit operation")
    return TranscriptEditProposalRead(operations=stored_operations)


def _prepare_processing(edit_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        job_reference = session.get(TranscriptEditJob, edit_id)
        if job_reference is None:
            return None
        meeting = session.exec(
            select(Meeting)
            .where(Meeting.id == job_reference.meeting_id)
            .with_for_update()
        ).first()
        if meeting is None:
            job = session.exec(
                select(TranscriptEditJob)
                .where(TranscriptEditJob.id == edit_id)
                .with_for_update()
            ).first()
            if job is not None and job.status == JOB_QUEUED:
                job.status = JOB_FAILED
                job.error = "Meeting not found"
                session.commit()
            return None
        job = session.exec(
            select(TranscriptEditJob)
            .where(TranscriptEditJob.id == edit_id)
            .with_for_update()
        ).first()
        if job is None or job.status != JOB_QUEUED or job.meeting_id != meeting.id:
            session.rollback()
            return None
        if meeting.status != "completed":
            _set_failed(session, job, "Meeting is not completed")
            return None
        current_revision = int(meeting.transcript_revision or 0)
        if current_revision != int(job.base_revision or 0):
            _set_failed(session, job, "Transcript changed before the edit was processed")
            return None
        try:
            scope = TranscriptEditScope.model_validate(job.scope)
            segments = _load_segments(session, meeting.id)
            profiles = sync_speaker_profiles(session, meeting.id, segments)
            _scope_segments(scope, segments, profiles)
        except (ValidationError, TranscriptEditValidationError) as exc:
            _set_failed(session, job, str(exc) or "Invalid transcript edit scope")
            return None
        segment_payload, profile_payload = _proposal_payload(segments, profiles, scope)
        job.status = JOB_PROCESSING
        job.error = None
        session.add(job)
        session.commit()
        return {
            "job_id": job.id,
            "meeting_id": meeting.id,
            "base_revision": int(job.base_revision or 0),
            "instruction": job.instruction,
            "scope": scope,
            "segments": segment_payload,
            "profiles": profile_payload,
        }


def _complete_processing(
    edit_id: str,
    snapshot: dict[str, Any],
    proposal: TranscriptEditProposal,
) -> None:
    with Session(engine) as session:
        job_reference = session.get(TranscriptEditJob, edit_id)
        if job_reference is None or job_reference.status != JOB_PROCESSING:
            return
        meeting = session.exec(
            select(Meeting)
            .where(Meeting.id == snapshot["meeting_id"])
            .with_for_update()
        ).first()
        job = session.exec(
            select(TranscriptEditJob)
            .where(TranscriptEditJob.id == edit_id)
            .with_for_update()
        ).first()
        if job is None or job.status != JOB_PROCESSING:
            session.rollback()
            return
        if meeting is None:
            _set_failed(session, job, "Meeting not found")
            return
        if meeting.status != "completed" or int(meeting.transcript_revision or 0) != snapshot["base_revision"]:
            _set_failed(session, job, "Transcript changed while the edit was processed")
            return
        segments = _load_segments(session, meeting.id)
        profiles = _load_profiles(session, meeting.id)
        try:
            stored = _build_stored_proposal(proposal, snapshot["scope"], segments, profiles)
        except TranscriptEditValidationError as exc:
            _set_failed(session, job, str(exc))
            return
        job.proposal = stored.model_dump(mode="json")
        job.status = JOB_COMPLETED
        job.error = None
        session.add(job)
        session.commit()


def process_edit_job(edit_id: str, llm_client: Any | None = None) -> str:
    try:
        snapshot = _prepare_processing(edit_id)
    except Exception:
        with Session(engine) as session:
            job = session.get(TranscriptEditJob, edit_id)
            if job is not None:
                _set_failed(session, job, "Transcript edit processing failed")
        return edit_id
    if snapshot is None:
        return edit_id
    try:
        proposal = generate_transcript_edit_proposal(
            instruction=snapshot["instruction"],
            transcript_segments=snapshot["segments"],
            scope=snapshot["scope"],
            speaker_profiles=snapshot["profiles"],
            client=llm_client,
        )
        if not isinstance(proposal, TranscriptEditProposal):
            proposal = TranscriptEditProposal.model_validate(proposal)
        _complete_processing(edit_id, snapshot, proposal)
    except TranscriptEditLLMError:
        with Session(engine) as session:
            job = session.get(TranscriptEditJob, edit_id)
            if job is not None:
                _set_failed(session, job, "Transcript edit model is unavailable")
    except Exception:
        with Session(engine) as session:
            job = session.get(TranscriptEditJob, edit_id)
            if job is not None:
                _set_failed(session, job, "Transcript edit processing failed")
    return edit_id


def _validate_before_values(
    proposal: TranscriptEditProposalRead,
    meeting: Meeting,
    job: TranscriptEditJob,
    session: Session,
) -> tuple[list[TranscriptSegment], dict[int, TranscriptSegment], dict[str, MeetingSpeaker]]:
    segments = _load_segments(session, meeting.id)
    profiles = sync_speaker_profiles(session, meeting.id, segments)
    try:
        scope = TranscriptEditScope.model_validate(job.scope)
    except ValidationError as exc:
        raise TranscriptEditValidationError("Stored transcript scope is invalid") from exc
    _scope_segments(scope, segments, profiles)
    segment_by_id = {segment.id: segment for segment in segments}
    profile_by_key = {profile.speaker_key: profile for profile in profiles}
    scoped_segments = _scope_segments(scope, segments, profiles)
    allowed_ids = {segment.id for segment in scoped_segments}
    scoped_keys = {_speaker_key(segment) for segment in scoped_segments}
    for operation in proposal.operations:
        if isinstance(operation, StoredReplaceTextOperation):
            if operation.segment_id not in allowed_ids:
                raise TranscriptEditConflict("A proposal segment is outside its scope")
            segment = segment_by_id.get(operation.segment_id)
            if segment is None:
                raise TranscriptEditConflict("A proposal segment no longer exists")
            before = operation.before
            if (
                before.get("segment_id") != operation.segment_id
                or before.get("text") != segment.text
                or before.get("speaker") != segment.speaker
                or before.get("start_time") != segment.start_time
                or before.get("end_time") != segment.end_time
                or before.get("words") != (segment.words or [])
            ):
                raise TranscriptEditConflict("A proposal segment changed before it could be applied")
        elif isinstance(operation, StoredRenameSpeakerOperation):
            if (
                scope.type == "speakers"
                and operation.speaker_key not in set(scope.speaker_keys or [])
            ) or (
                scope.type == "segments"
                and operation.speaker_key not in scoped_keys
            ):
                raise TranscriptEditConflict("A proposal speaker is outside its scope")
            profile = profile_by_key.get(operation.speaker_key)
            if profile is None:
                raise TranscriptEditConflict("A proposal speaker no longer exists")
            before = operation.before
            if before.get("speaker_key") != operation.speaker_key or before.get("display_name") != profile.display_name:
                raise TranscriptEditConflict("A proposal speaker changed before it could be applied")
        elif isinstance(operation, StoredReassignSpeakerOperation):
            if any(segment_id not in allowed_ids for segment_id in operation.segment_ids):
                raise TranscriptEditConflict("A proposal segment is outside its scope")
            if operation.target_speaker_key not in profile_by_key:
                raise TranscriptEditConflict("A proposal target speaker no longer exists")
            before_segments = operation.before.get("segments")
            if not isinstance(before_segments, list):
                raise TranscriptEditConflict("A proposal speaker assignment is invalid")
            before_ids = [
                item.get("segment_id")
                for item in before_segments
                if isinstance(item, dict)
            ]
            if (
                any(not isinstance(segment_id, int) for segment_id in before_ids)
                or len(before_ids) != len(operation.segment_ids)
                or set(before_ids) != set(operation.segment_ids)
            ):
                raise TranscriptEditConflict("A proposal speaker assignment is invalid")
            for before_segment in before_segments:
                if not isinstance(before_segment, dict):
                    raise TranscriptEditConflict("A proposal speaker assignment is invalid")
                segment_id = before_segment.get("segment_id")
                segment = segment_by_id.get(segment_id)
                if segment is None or segment.speaker != before_segment.get("speaker"):
                    raise TranscriptEditConflict("A proposal speaker assignment changed before it could be applied")
                if operation.target_speaker_key not in profile_by_key:
                    raise TranscriptEditConflict("A proposal target speaker no longer exists")
    return segments, segment_by_id, profile_by_key


def apply_edit_job(
    session: Session,
    meeting_id: int,
    edit_id: str,
    user_id: int,
    expected_revision: int | None = None,
) -> TranscriptEditJob:
    session.expire_all()
    try:
        meeting, job = _get_owned_job(session, meeting_id, edit_id, user_id, lock=True)
        if job.status == JOB_APPLIED:
            session.rollback()
            return job
        if job.status not in READY_STATUSES:
            raise TranscriptEditConflict("Transcript edit proposal is not ready")
        if expected_revision is not None and expected_revision != int(job.base_revision or 0):
            raise TranscriptEditConflict("Transcript edit base revision does not match")
        if meeting.status != "completed":
            raise TranscriptEditConflict("Transcript edits require a completed meeting")
        current_revision = int(meeting.transcript_revision or 0)
        if current_revision != int(job.base_revision or 0):
            raise TranscriptEditConflict("Transcript has changed since this proposal was created")
        if not job.proposal:
            raise TranscriptEditConflict("Transcript edit has no proposal")
        try:
            proposal = TranscriptEditProposalRead.model_validate(job.proposal)
        except ValidationError as exc:
            raise TranscriptEditValidationError("Stored transcript proposal is invalid") from exc

        segments, segment_by_id, profile_by_key = _validate_before_values(
            proposal, meeting, job, session
        )
        now = datetime.now(timezone.utc)
        changed = False
        for operation in proposal.operations:
            if isinstance(operation, StoredReplaceTextOperation):
                segment = segment_by_id[operation.segment_id]
                if segment.text != operation.replacement_text:
                    segment.text = operation.replacement_text
                    segment.text_edited = True
                    segment.word_alignment_valid = False
                    changed = True
            elif isinstance(operation, StoredRenameSpeakerOperation):
                profile = profile_by_key[operation.speaker_key]
                if profile.display_name != operation.display_name:
                    profile.display_name = operation.display_name
                    profile.updated_at = now
                    changed = True
            elif isinstance(operation, StoredReassignSpeakerOperation):
                if operation.target_speaker_key not in profile_by_key:
                    raise TranscriptEditConflict("A proposal target speaker no longer exists")
                for segment_id in operation.segment_ids:
                    segment = segment_by_id[segment_id]
                    if segment.speaker != operation.target_speaker_key:
                        segment.speaker = operation.target_speaker_key
                        changed = True
                    updated_words = []
                    for word in segment.words or []:
                        if isinstance(word, dict):
                            if word.get("speaker") != operation.target_speaker_key:
                                changed = True
                            updated_words.append(
                                {**word, "speaker": operation.target_speaker_key}
                            )
                        else:
                            updated_words.append(word)
                    segment.words = updated_words

        sync_speaker_profiles(session, meeting.id, segments)
        if changed:
            meeting.transcript_revision = current_revision + 1
            meeting.transcript_text = serialize_transcript(segments)
            meeting.transliterated_text = None
        job.status = JOB_APPLIED
        job.applied_at = now
        job.error = None
        session.add(meeting)
        session.add(job)
        session.commit()
    except Exception:
        session.rollback()
        raise
    try:
        session.refresh(job)
    except Exception:
        pass
    return job


process_transcript_edit_job = process_edit_job


def discard_edit_job(
    session: Session,
    meeting_id: int,
    edit_id: str,
    user_id: int,
) -> TranscriptEditJob:
    session.expire_all()
    try:
        _, job = _get_owned_job(session, meeting_id, edit_id, user_id, lock=True)
        if job.status == JOB_APPLIED:
            raise TranscriptEditConflict("An applied transcript edit cannot be discarded")
        if job.status == JOB_DISCARDED:
            session.rollback()
            return job
        job.status = JOB_DISCARDED
        job.error = None
        session.add(job)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return job

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unittest.mock import patch

from app.models import Meeting, MeetingSpeaker, TranscriptEditJob, TranscriptSegment, User


SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON


class ContractFakeCompletions:
    def __init__(self, proposal):
        self.proposal = proposal

    def parse(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=self.proposal))]
        )


class ContractFakeLLM:
    def __init__(self, proposal):
        completions = ContractFakeCompletions(proposal)
        self.chat = SimpleNamespace(completions=completions)
        self.beta = SimpleNamespace(chat=self.chat)


@pytest.fixture
def api_client(monkeypatch):
    from app.core.config import settings

    settings.OPENAI_API_KEY = "test-key"
    settings.OPENAI_MODEL = "test-model"
    from app.api import deps
    from app.api.v1.endpoints import transcript_edits as endpoint
    from app.services import transcript_edit_jobs as edit_jobs
    from app.main import app

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Meeting.__table__,
            TranscriptSegment.__table__,
            TranscriptEditJob.__table__,
            MeetingSpeaker.__table__,
        ],
    )
    session = Session(engine)
    user = User(id=1, email="api@example.com", supabase_id="api-supabase-id")
    meeting = Meeting(
        owner_id=1,
        title="API edit meeting",
        status="completed",
        created_at=datetime.now(timezone.utc),
        transcript_revision=0,
        derived_transcript_revision=0,
    )
    session.add(user)
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    segment = TranscriptSegment(
        meeting_id=meeting.id,
        start_time=0.0,
        end_time=1.0,
        text="Original",
        speaker="SPEAKER_A",
    )
    session.add(segment)
    session.commit()

    previous_overrides = dict(app.dependency_overrides)
    monkeypatch.setattr(edit_jobs, "engine", engine)
    app.dependency_overrides[deps.get_db] = lambda: session
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    monkeypatch.setattr(endpoint, "ensure_available", lambda: None)
    client = TestClient(app)
    yield client, session, meeting, user
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)
    session.close()
    engine.dispose()


def test_create_transcript_edit_contract_returns_202_and_queues(api_client, monkeypatch):
    client, session, meeting, user = api_client
    with patch("app.worker.process_transcript_edit.delay") as delay:
        response = client.post(
            f"/api/v1/meetings/{meeting.id}/transcript-edits",
            headers={"Authorization": "Bearer test"},
            json={
                "instruction": "Replace the selected wording",
                "scope": {"type": "segments", "segment_ids": [1]},
            },
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["base_revision"] == 0
    assert body["proposal"] is None
    delay.assert_called_once_with(body["id"])


def test_create_transcript_edit_rejects_unknown_fields_and_oversized_instruction(api_client):
    client, _, meeting, _ = api_client
    unknown = client.post(
        f"/api/v1/meetings/{meeting.id}/transcript-edits",
        json={
            "instruction": "Fix this",
            "scope": {"type": "whole_transcript"},
            "operations": [{"operation": "merge_speakers"}],
        },
    )
    assert unknown.status_code == 422
    oversized = client.post(
        f"/api/v1/meetings/{meeting.id}/transcript-edits",
        json={
            "instruction": "x" * 4001,
            "scope": {"type": "whole_transcript"},
        },
    )
    assert oversized.status_code == 422


def test_create_transcript_edit_returns_503_when_llm_is_unavailable(api_client, monkeypatch):
    client, _, meeting, _ = api_client
    from app.api.v1.endpoints import transcript_edits as endpoint
    from app.services.transcript_edit_llm import TranscriptEditLLMUnavailable

    monkeypatch.setattr(
        endpoint,
        "ensure_available",
        lambda: (_ for _ in ()).throw(TranscriptEditLLMUnavailable()),
    )
    response = client.post(
        f"/api/v1/meetings/{meeting.id}/transcript-edits",
        json={"instruction": "Fix this", "scope": {"type": "whole_transcript"}},
    )
    assert response.status_code == 503


def test_create_transcript_edit_hides_unowned_meeting(api_client, monkeypatch):
    client, _, meeting, _ = api_client
    from app.api import deps
    from app.models import User

    other_user = User(id=2, email="other@example.com", supabase_id="other-supabase-id")
    client.app.dependency_overrides[deps.get_current_active_user] = lambda: other_user
    response = client.post(
        f"/api/v1/meetings/{meeting.id}/transcript-edits",
        json={"instruction": "Fix this", "scope": {"type": "whole_transcript"}},
    )
    assert response.status_code == 404


def test_apply_and_discard_transcript_edit_contract(api_client):
    client, session, meeting, user = api_client
    from sqlmodel import select
    from app.schemas.transcript_edits import (
        TranscriptEditCreateRequest,
        TranscriptEditProposal,
        TranscriptEditScope,
    )
    from app.services import transcript_edit_jobs as edit_jobs

    segment = session.exec(
        select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id)
    ).first()
    request = TranscriptEditCreateRequest(
        instruction="Replace the original text",
        scope=TranscriptEditScope(type="whole_transcript"),
    )
    job = edit_jobs.create_edit_job(session, meeting.id, user.id, request)
    proposal = TranscriptEditProposal.model_validate(
        {
            "operations": [
                {
                    "operation": "replace_text",
                    "segment_id": segment.id,
                    "replacement_text": "Edited text",
                }
            ]
        }
    )
    edit_jobs.process_edit_job(job.id, llm_client=ContractFakeLLM(proposal))
    applied = client.post(
        f"/api/v1/meetings/{meeting.id}/transcript-edits/{job.id}/apply",
        json={"expected_revision": 0},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    repeated = client.post(
        f"/api/v1/meetings/{meeting.id}/transcript-edits/{job.id}/apply"
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "applied"

    second = edit_jobs.create_edit_job(session, meeting.id, user.id, request)
    edit_jobs.process_edit_job(second.id, llm_client=ContractFakeLLM(proposal))
    discarded = client.post(
        f"/api/v1/meetings/{meeting.id}/transcript-edits/{second.id}/discard",
        json={},
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["status"] == "discarded"

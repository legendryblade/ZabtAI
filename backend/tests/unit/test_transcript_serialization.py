# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
from datetime import datetime
from unittest.mock import patch

from app.models import Meeting, TranscriptSegment
from app.services.transcript import serialize_transcript


def test_serialize_transcript_orders_segments_and_handles_missing_speaker():
    segments = [
        TranscriptSegment(
            id=22,
            start_time=12.0,
            end_time=13.0,
            text="second",
            speaker=None,
        ),
        TranscriptSegment(
            id=11,
            start_time=1.0,
            end_time=2.5,
            text="first",
            speaker="SPEAKER_00",
        ),
    ]

    assert serialize_transcript(segments) == (
        "[00:01.0 - 00:02.5] SPEAKER_00: first\n[00:12.0 - 00:13.0] SPEAKER_UNKNOWN: second"
    )


def test_build_meeting_response_exposes_segment_ids_in_time_order():
    try:
        from app.api.v1.endpoints.meetings import _build_meeting_response
    except (ImportError, OSError) as exc:
        import pytest

        pytest.skip(f"Meeting endpoint dependencies unavailable: {exc}")

    meeting = Meeting(
        id=7,
        owner_id=1,
        title="Transcript ordering",
        created_at=datetime.utcnow(),
        status="completed",
        segments=[
            TranscriptSegment(
                id=22,
                start_time=12.0,
                end_time=13.0,
                text="second",
                speaker=None,
            ),
            TranscriptSegment(
                id=11,
                start_time=1.0,
                end_time=2.0,
                text="first",
                speaker="SPEAKER_00",
            ),
        ],
    )

    with (
        patch(
            "app.api.v1.endpoints.meetings.intelligence_service.get_highlights",
            return_value=[],
        ),
        patch(
            "app.api.v1.endpoints.meetings.intelligence_service.get_layout_hint",
            return_value="list",
        ),
    ):
        response = _build_meeting_response(meeting)

    assert [segment.id for segment in response.segments] == [11, 22]
    assert [segment.text for segment in response.segments] == ["first", "second"]
    assert response.segments[1].speaker is None

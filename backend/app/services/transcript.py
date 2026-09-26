# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
from collections.abc import Iterable
from math import isfinite

from app.models import TranscriptSegment


def _format_timestamp(seconds: float) -> str:
    value = float(seconds)
    if not isfinite(value) or value < 0:
        value = 0.0
    total_tenths = int(value * 10 + 0.5)
    hours, remainder = divmod(total_tenths, 36000)
    minutes, remainder = divmod(remainder, 600)
    whole_seconds, tenths = divmod(remainder, 10)
    if hours:
        return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{tenths}"
    return f"{minutes:02d}:{whole_seconds:02d}.{tenths}"


def serialize_transcript(segments: Iterable[TranscriptSegment]) -> str:
    lines = []
    for segment in sorted(
        segments,
        key=lambda item: (item.start_time, item.id or 0),
    ):
        speaker = (segment.speaker or "SPEAKER_UNKNOWN").strip() or "SPEAKER_UNKNOWN"
        text = (segment.text or "").strip()
        start = _format_timestamp(segment.start_time)
        end = _format_timestamp(segment.end_time)
        lines.append(f"[{start} - {end}] {speaker}: {text}")
    return "\n".join(lines)

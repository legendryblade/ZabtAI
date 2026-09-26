# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
"""Groq Transcription Client — hosted Whisper large-v3 via the Groq OpenAI-compatible API.

Implements the TranscriptionProvider protocol. Requires a local audio file
(stage_download always runs for this backend). No diarization: speaker labels
are left unset (pending a future free/local diarization option).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from app.core.config import settings
from app.models import TranscriptionType
from app.services.transcription.types import (
    ResultSegment,
    TranscriptionConfig,
    TranscriptionResult,
    WordTimestamp,
)

logger = logging.getLogger(__name__)

_CONTENT_TYPES = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


class GroqTranscriptionClient:
    """TranscriptionProvider that posts audio to Groq's audio/transcriptions endpoint."""

    def __init__(self) -> None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError(
                "TRANSCRIPTION_BACKEND=groq but GROQ_API_KEY is missing. "
                "Set it in your .env file (https://console.groq.com/keys)."
            )
        self._base_url = settings.GROQ_BASE_URL.rstrip("/")
        self._model = settings.GROQ_TRANSCRIBE_MODEL
        self._timeout = settings.GROQ_TIMEOUT
        self._max_file_bytes = settings.GROQ_MAX_FILE_MB * 1024 * 1024
        self._http = httpx.Client(timeout=self._timeout)
        logger.info(
            "GroqTranscriptionClient model=%s max_file_mb=%s",
            self._model,
            settings.GROQ_MAX_FILE_MB,
        )

    def get_provider_name(self) -> str:
        return "groq"

    def process_audio(
        self,
        audio_path: str,
        config: TranscriptionConfig | None = None,
        on_status_change: Callable[[str], None] | None = None,
    ) -> TranscriptionResult:
        config = config or TranscriptionConfig()

        if config.transcription_type == TranscriptionType.MEDICAL:
            raise NotImplementedError(
                "Medical transcription (MedASR) is not available on Groq. "
                "Use TRANSCRIPTION_BACKEND=gpu-local or runpod for medical mode."
            )

        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if on_status_change:
            on_status_change("transcribing")

        upload_path = audio_path
        temp_compressed: str | None = None
        try:
            if os.path.getsize(audio_path) > self._max_file_bytes:
                temp_compressed = self._compress(audio_path)
                upload_path = temp_compressed

            payload = self._transcribe(upload_path, config, on_status_change)
            return self._parse_response(payload)
        finally:
            if temp_compressed and os.path.exists(temp_compressed):
                os.remove(temp_compressed)

    async def transcribe_chunk(self, data: bytes) -> str:
        raise NotImplementedError(
            "Groq provider does not support real-time chunk transcription."
        )

    # ── internals ──────────────────────────────────────────────────────────

    def _transcribe(
        self,
        file_path: str,
        config: TranscriptionConfig,
        on_status_change: Callable[[str], None] | None,
    ) -> dict:
        ext = Path(file_path).suffix.lower() or ".wav"
        content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
        url = f"{self._base_url}/audio/transcriptions"

        data: list[tuple[str, str]] = [
            ("model", self._model),
            ("response_format", "verbose_json"),
            ("temperature", "0"),
            ("timestamp_granularities[]", "segment"),
            ("timestamp_granularities[]", "word"),
        ]
        if config.language:
            data.append(("language", config.language))

        with open(file_path, "rb") as audio_file:
            files = {"file": (Path(file_path).name, audio_file, content_type)}
            if on_status_change:
                on_status_change("transcribing")
            resp = self._http.post(
                url,
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                data=data,
                files=files,
            )

        if resp.status_code == 429:
            raise RuntimeError(
                "Groq rate limit exceeded (free tier: 20 RPM / 2,000 RPD for whisper). "
                "Retry later or upgrade at console.groq.com."
            )
        if resp.status_code in (401, 403):
            raise RuntimeError("Groq auth failed — check GROQ_API_KEY.")
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Groq transcription failed ({resp.status_code}): {resp.text[:500]}"
            )

        return resp.json()

    @staticmethod
    def _parse_response(payload: dict) -> TranscriptionResult:
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Groq response type: {type(payload)}")

        raw_segments = payload.get("segments") or []
        raw_words = payload.get("words") or []

        words = [
            WordTimestamp(
                word=str(w.get("word", "")).strip(),
                start=float(w.get("start", 0.0) or 0.0),
                end=float(w.get("end", 0.0) or 0.0),
                speaker_label=None,
                confidence=None,
            )
            for w in raw_words
        ]

        segments: list[ResultSegment] = []
        for seg in raw_segments:
            start = float(seg.get("start", 0.0) or 0.0)
            end = float(seg.get("end", 0.0) or 0.0)
            seg_words = [
                w for w in words if w.start >= start - 0.05 and w.end <= end + 0.05
            ]
            segments.append(
                ResultSegment(
                    start=start,
                    end=end,
                    text=str(seg.get("text", "")).strip(),
                    speaker=None,  # no diarization on Groq yet
                    words=seg_words,
                )
            )

        # Fallback: no segments but full text → single segment
        text = str(payload.get("text", "")).strip()
        if not segments and text:
            end = words[-1].end if words else 0.0
            segments = [
                ResultSegment(start=0.0, end=end, text=text, speaker=None, words=words)
            ]

        language = str(payload.get("language", "en") or "en")
        # Groq may return full names ("english") — map to a whisper-style code.
        if len(language) > 3:
            language = language.lower()[:2]

        duration = float(payload.get("duration", 0.0) or 0.0)
        if not duration and segments:
            duration = segments[-1].end

        return TranscriptionResult(
            text=text or " ".join(s.text for s in segments),
            language=language,
            segments=segments,
            provider_name="groq",
            recognition_method=f"groq_{settings.GROQ_TRANSCRIBE_MODEL}",
            audio_duration_seconds=duration,
            estimated_cost=0.0,  # free tier
        )

    def _compress(self, audio_path: str) -> str:
        """Re-encode to mono 64 kbps MP3 to fit under the upload size cap."""
        fd, out_path = tempfile.mkstemp(suffix=".mp3", prefix="zabt_groq_")
        os.close(fd)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            audio_path,
            "-vn",
            "-ac",
            "1",
            "-b:a",
            "64k",
            out_path,
        ]
        logger.info(
            "Groq file exceeds %d MB — re-encoding to 64k mono mp3: %s",
            settings.GROQ_MAX_FILE_MB,
            audio_path,
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        except FileNotFoundError as e:
            if os.path.exists(out_path):
                os.remove(out_path)
            raise RuntimeError(
                "ffmpeg is required to compress large audio for Groq upload."
            ) from e
        except subprocess.CalledProcessError as e:
            if os.path.exists(out_path):
                os.remove(out_path)
            raise RuntimeError(
                "ffmpeg re-encode failed for Groq upload: "
                f"{e.stderr.decode(errors='replace')[:300]}"
            ) from e

        if os.path.getsize(out_path) > self._max_file_bytes:
            size_mb = os.path.getsize(out_path) // (1024 * 1024)
            os.remove(out_path)
            raise RuntimeError(
                f"Audio still {size_mb} MB after compression (limit "
                f"{settings.GROQ_MAX_FILE_MB} MB). Shorten the file or raise "
                "GROQ_MAX_FILE_MB."
            )
        return out_path

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
"""Deepgram Transcription Client — hosted Nova ASR + speaker diarization.

Implements the TranscriptionProvider protocol. Single POST to /v1/listen returns
both the transcript and speaker labels (when DEEPGRAM_DIARIZE=true). Requires a
local audio file (stage_download always runs for this backend).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

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
    ".aiff": "audio/aiff",
    ".caf": "audio/caf",
}


_DEEPGRAM_DETECTABLE_LANGUAGES = {
    "bg",
    "ca",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "fi",
    "fr",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "lt",
    "lv",
    "ms",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sk",
    "th",
    "tr",
    "uk",
    "vi",
    "zh",
}


def _speaker_label(raw: Any) -> str | None:
    """Deepgram returns speaker as int (0, 1, …) — normalize to SPEAKER_00 style."""
    if raw is None:
        return None
    try:
        return f"SPEAKER_{int(raw):02d}"
    except (TypeError, ValueError):
        text = str(raw).strip()
        return text or None


def _word_from_raw(w: dict) -> WordTimestamp:
    speaker = _speaker_label(w.get("speaker"))
    return WordTimestamp(
        word=str(w.get("punctuated_word") or w.get("word") or "").strip(),
        start=float(w.get("start", 0.0) or 0.0),
        end=float(w.get("end", 0.0) or 0.0),
        speaker_label=speaker,
        confidence=float(w["confidence"]) if w.get("confidence") is not None else None,
    )


class DeepgramTranscriptionClient:
    """TranscriptionProvider that posts audio to Deepgram's /v1/listen endpoint."""

    def __init__(self) -> None:
        if not settings.DEEPGRAM_API_KEY:
            raise RuntimeError(
                "TRANSCRIPTION_BACKEND=deepgram but DEEPGRAM_API_KEY is missing. "
                "Set it in your .env file (https://console.deepgram.com/keys)."
            )
        self._base_url = settings.DEEPGRAM_BASE_URL.rstrip("/")
        self._model = settings.DEEPGRAM_MODEL
        self._diarize = settings.DEEPGRAM_DIARIZE
        self._timeout = settings.DEEPGRAM_TIMEOUT
        self._max_file_bytes = settings.DEEPGRAM_MAX_FILE_MB * 1024 * 1024
        self._http = httpx.Client(timeout=self._timeout)
        logger.info(
            "DeepgramTranscriptionClient model=%s diarize=%s max_file_mb=%s",
            self._model,
            self._diarize,
            settings.DEEPGRAM_MAX_FILE_MB,
        )

    def get_provider_name(self) -> str:
        return "deepgram"

    def process_audio(
        self,
        audio_path: str,
        config: TranscriptionConfig | None = None,
        on_status_change: Callable[[str], None] | None = None,
    ) -> TranscriptionResult:
        config = config or TranscriptionConfig()

        if config.transcription_type == TranscriptionType.MEDICAL:
            raise NotImplementedError(
                "Medical transcription (MedASR) is not available on Deepgram. "
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

            if self._diarize and on_status_change:
                on_status_change("diarizing")

            payload = self._transcribe(upload_path, config)
            return self._parse_response(payload, model=self._model)
        finally:
            if temp_compressed and os.path.exists(temp_compressed):
                os.remove(temp_compressed)

    async def transcribe_chunk(self, data: bytes) -> str:
        raise NotImplementedError(
            "Deepgram provider does not support real-time chunk transcription."
        )

    # ── internals ──────────────────────────────────────────────────────────

    def _transcribe(self, file_path: str, config: TranscriptionConfig) -> dict:
        ext = Path(file_path).suffix.lower() or ".wav"
        content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
        url = f"{self._base_url}/v1/listen"

        params: list[tuple[str, str]] = [
            ("model", self._model),
            ("smart_format", "true"),
            ("punctuate", "true"),
            ("utterances", "true"),  # segment-level turns for ResultSegment
        ]
        if self._diarize:
            # Current recommended API; diarize=true is deprecated (v1 only).
            params.append(("diarize_model", "latest"))

        if config.language:
            # Whisper-style codes (en, ur, …) are valid BCP-47 for Deepgram.
            params.append(("language", config.language))
            params.append(("detect_language", "false"))
        elif config.allowed_languages:
            # Restrict automatic detection to the user's allowed language set.
            # Only pass codes Deepgram supports for detect_language; ignore others.
            detectable = sorted(
                code for code in config.allowed_languages if code in _DEEPGRAM_DETECTABLE_LANGUAGES
            )
            if detectable:
                for code in detectable:
                    params.append(("detect_language", code))
            else:
                # No allowed language is Deepgram-detectable (e.g. only "ur").
                # Forcing one of them is safer than unrestricted detection,
                # which could return a language outside the allowed set.
                fallback = sorted(config.allowed_languages)[0]
                params.append(("language", fallback))
                params.append(("detect_language", "false"))
        else:
            params.append(("detect_language", "true"))

        def _iter_file(file_obj, chunk_size: int = 1024 * 1024):
            while True:
                chunk = file_obj.read(chunk_size)
                if not chunk:
                    break
                yield chunk

        with open(file_path, "rb") as audio_file:
            resp = self._http.post(
                url,
                headers={
                    "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                    "Content-Type": content_type,
                },
                params=params,
                content=_iter_file(audio_file),
            )

        if resp.status_code == 429:
            raise RuntimeError(
                "Deepgram rate limit exceeded. Retry later or check "
                "console.deepgram.com usage/limits."
            )
        if resp.status_code in (401, 403):
            raise RuntimeError("Deepgram auth failed — check DEEPGRAM_API_KEY.")
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Deepgram transcription failed ({resp.status_code}): {resp.text[:500]}"
            )

        return resp.json()

    @staticmethod
    def _parse_response(payload: dict, model: str = "nova-3") -> TranscriptionResult:
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Deepgram response type: {type(payload)}")

        results = payload.get("results") or {}
        channels = results.get("channels") or []
        channel = channels[0] if channels else {}
        alternatives = channel.get("alternatives") or []
        alternative = alternatives[0] if alternatives else {}

        raw_words = alternative.get("words") or []
        words = [_word_from_raw(w) for w in raw_words]

        # Prefer utterances (speaker turns) as segments; fall back to word runs.
        raw_utterances = results.get("utterances") or []
        segments: list[ResultSegment] = []

        if raw_utterances:
            for utt in raw_utterances:
                start = float(utt.get("start", 0.0) or 0.0)
                end = float(utt.get("end", 0.0) or 0.0)
                speaker = _speaker_label(utt.get("speaker"))
                utt_words_raw = utt.get("words") or []
                utt_words = (
                    [_word_from_raw(w) for w in utt_words_raw]
                    if utt_words_raw
                    else [w for w in words if w.start >= start - 0.05 and w.end <= end + 0.05]
                )
                segments.append(
                    ResultSegment(
                        start=start,
                        end=end,
                        text=str(utt.get("transcript", "")).strip(),
                        speaker=speaker,
                        words=utt_words,
                    )
                )
        elif words:
            # Group consecutive words by speaker into segments.
            current_speaker = words[0].speaker_label
            current_start = words[0].start
            current_words: list[WordTimestamp] = []

            def _flush(end: float, speaker: str | None, ws: list[WordTimestamp]) -> None:
                if not ws:
                    return
                text = " ".join(w.word for w in ws if w.word)
                segments.append(
                    ResultSegment(
                        start=current_start,
                        end=end,
                        text=text.strip(),
                        speaker=speaker,
                        words=list(ws),
                    )
                )

            for w in words:
                if w.speaker_label != current_speaker and current_words:
                    _flush(current_words[-1].end, current_speaker, current_words)
                    current_start = w.start
                    current_words = []
                current_speaker = w.speaker_label
                current_words.append(w)
            if current_words:
                _flush(current_words[-1].end, current_speaker, current_words)

        text = str(alternative.get("transcript", "") or "").strip()
        if not text:
            text = " ".join(s.text for s in segments).strip()

        language = (
            channel.get("detected_language")
            or alternative.get("detected_language")
            or payload.get("detected_language")
            or "en"
        )
        language = str(language)
        # Normalize BCP-47 (en-US) to whisper-style codes (en) for downstream use.
        if "-" in language:
            language = language.split("-", 1)[0].lower()
        elif len(language) > 3:
            language = language.lower()[:2]

        duration = float((payload.get("metadata") or {}).get("duration", 0.0) or 0.0)
        if not duration and segments:
            duration = segments[-1].end

        # Rough free-credit burn estimate: Nova-3 pre-recorded ≈ $0.0043/min
        # (diarization is included on pre-recorded; multilingual may be $0.0052/min).
        minutes = duration / 60.0
        estimated_cost = round(minutes * 0.0043, 6) if duration else 0.0

        return TranscriptionResult(
            text=text,
            language=language,
            segments=segments,
            provider_name="deepgram",
            recognition_method=f"deepgram_{model}",
            audio_duration_seconds=duration,
            estimated_cost=estimated_cost,
        )

    def _compress(self, audio_path: str) -> str:
        """Re-encode to mono 96 kbps MP3 when over the configured size cap."""
        fd, out_path = tempfile.mkstemp(suffix=".mp3", prefix="zabt_dg_")
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
            "96k",
            out_path,
        ]
        logger.info(
            "Deepgram file exceeds %d MB — re-encoding to 96k mono mp3: %s",
            settings.DEEPGRAM_MAX_FILE_MB,
            audio_path,
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        except FileNotFoundError as e:
            if os.path.exists(out_path):
                os.remove(out_path)
            raise RuntimeError(
                "ffmpeg is required to compress large audio for Deepgram upload."
            ) from e
        except subprocess.CalledProcessError as e:
            if os.path.exists(out_path):
                os.remove(out_path)
            raise RuntimeError(
                "ffmpeg re-encode failed for Deepgram upload: "
                f"{e.stderr.decode(errors='replace')[:300]}"
            ) from e

        if os.path.getsize(out_path) > self._max_file_bytes:
            size_mb = os.path.getsize(out_path) // (1024 * 1024)
            os.remove(out_path)
            raise RuntimeError(
                f"Audio still {size_mb} MB after compression (limit "
                f"{settings.DEEPGRAM_MAX_FILE_MB} MB). Shorten the file or raise "
                "DEEPGRAM_MAX_FILE_MB."
            )
        return out_path

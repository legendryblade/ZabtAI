# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
"""TranscriptionProviderFactory — dispatches by TRANSCRIPTION_BACKEND setting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import settings
from app.models import UserTier, TranscriptionBackend
from app.services.transcription.types import TranscriptionConfig

if TYPE_CHECKING:
    from app.services.transcription.provider import TranscriptionProvider

logger = logging.getLogger(__name__)

_gpu_client: TranscriptionProvider | None = None
_groq_client: TranscriptionProvider | None = None
_deepgram_client: TranscriptionProvider | None = None


def _get_gpu_client(backend: TranscriptionBackend) -> TranscriptionProvider:
    global _gpu_client
    if _gpu_client is None:
        from app.services.transcription.gpu_client import GpuTranscriptionClient

        _gpu_client = GpuTranscriptionClient(backend=backend)
    return _gpu_client


def _get_groq_client() -> TranscriptionProvider:
    global _groq_client
    if _groq_client is None:
        from app.services.transcription.groq_client import GroqTranscriptionClient

        _groq_client = GroqTranscriptionClient()
    return _groq_client


def _get_deepgram_client() -> TranscriptionProvider:
    global _deepgram_client
    if _deepgram_client is None:
        from app.services.transcription.deepgram_client import DeepgramTranscriptionClient

        _deepgram_client = DeepgramTranscriptionClient()
    return _deepgram_client


def _validate_runpod_config() -> None:
    """Fail fast if RunPod is selected but credentials are missing."""
    missing = []
    if not settings.RUNPOD_API_KEY:
        missing.append("RUNPOD_API_KEY")
    if not settings.RUNPOD_ENDPOINT_ID:
        missing.append("RUNPOD_ENDPOINT_ID")
    if missing:
        raise RuntimeError(
            f"TRANSCRIPTION_BACKEND=runpod but missing required env vars: {', '.join(missing)}. "
            "Set these in your .env file or environment."
        )


def _validate_groq_config() -> None:
    """Fail fast if Groq is selected but the API key is missing."""
    if not settings.GROQ_API_KEY:
        raise RuntimeError(
            "TRANSCRIPTION_BACKEND=groq but missing required env var: GROQ_API_KEY. "
            "Set it in your .env file (https://console.groq.com/keys)."
        )


def _validate_deepgram_config() -> None:
    """Fail fast if Deepgram is selected but the API key is missing."""
    if not settings.DEEPGRAM_API_KEY:
        raise RuntimeError(
            "TRANSCRIPTION_BACKEND=deepgram but missing required env var: DEEPGRAM_API_KEY. "
            "Set it in your .env file (https://console.deepgram.com/keys)."
        )


def get_provider(
    user_tier: UserTier | None = None,
) -> TranscriptionProvider:
    """Return the active TranscriptionProvider based on TRANSCRIPTION_BACKEND setting."""
    backend = settings.TRANSCRIPTION_BACKEND

    if backend == TranscriptionBackend.RUNPOD:
        _validate_runpod_config()
    elif backend == TranscriptionBackend.GROQ:
        _validate_groq_config()
        return _get_groq_client()
    elif backend == TranscriptionBackend.DEEPGRAM:
        _validate_deepgram_config()
        return _get_deepgram_client()

    return _get_gpu_client(backend)


def build_config(
    user_tier: UserTier | None = None,
    language: str | None = None,
    allowed_languages: set[str] | None = None,
) -> TranscriptionConfig:
    """Build a TranscriptionConfig with diarization settings from config."""
    return TranscriptionConfig(
        min_speakers=settings.DIARIZATION_MIN_SPEAKERS,
        max_speakers=settings.DIARIZATION_MAX_SPEAKERS,
        language=language,
        allowed_languages=allowed_languages,
    )

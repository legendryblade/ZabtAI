# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
"""Unit tests for GroqTranscriptionClient response parsing and factory wiring."""

import pytest
from unittest.mock import patch

from app.models import TranscriptionBackend, TranscriptionType
from app.services.transcription.groq_client import GroqTranscriptionClient
from app.services.transcription.types import TranscriptionConfig


SAMPLE_PAYLOAD = {
    "text": " Hello world. How are you?",
    "language": "english",
    "duration": 5.5,
    "segments": [
        {"id": 0, "start": 0.0, "end": 2.5, "text": " Hello world."},
        {"id": 1, "start": 2.5, "end": 5.5, "text": " How are you?"},
    ],
    "words": [
        {"word": "Hello", "start": 0.0, "end": 0.6},
        {"word": "world.", "start": 0.7, "end": 1.4},
        {"word": "How", "start": 2.5, "end": 2.9},
        {"word": "are", "start": 3.0, "end": 3.3},
        {"word": "you?", "start": 3.4, "end": 3.9},
    ],
}


class TestGroqParseResponse:
    def test_maps_segments_and_words(self):
        result = GroqTranscriptionClient._parse_response(SAMPLE_PAYLOAD)

        assert result.provider_name == "groq"
        assert result.language == "en"  # "english" → "en"
        assert result.audio_duration_seconds == 5.5
        assert result.estimated_cost == 0.0
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello world."
        assert result.segments[0].speaker is None
        assert len(result.segments[0].words) == 2
        assert len(result.segments[1].words) == 3

    def test_fallback_single_segment_without_segments_array(self):
        result = GroqTranscriptionClient._parse_response(
            {"text": "Only full text.", "language": "en", "words": []}
        )
        assert len(result.segments) == 1
        assert result.segments[0].text == "Only full text."

    def test_duration_from_last_segment_when_missing(self):
        result = GroqTranscriptionClient._parse_response(
            {
                "text": "Hi",
                "language": "en",
                "segments": [{"start": 0.0, "end": 12.0, "text": "Hi"}],
            }
        )
        assert result.audio_duration_seconds == 12.0


class TestGroqClientInit:
    def test_missing_api_key_raises(self):
        with patch(
            "app.services.transcription.groq_client.settings"
        ) as mock_settings:
            mock_settings.GROQ_API_KEY = ""
            with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
                GroqTranscriptionClient()

    def test_medical_mode_rejected(self):
        with patch(
            "app.services.transcription.groq_client.settings"
        ) as mock_settings:
            mock_settings.GROQ_API_KEY = "gsk_test"
            mock_settings.GROQ_BASE_URL = "https://api.groq.com/openai/v1"
            mock_settings.GROQ_TRANSCRIBE_MODEL = "whisper-large-v3"
            mock_settings.GROQ_TIMEOUT = 60
            mock_settings.GROQ_MAX_FILE_MB = 25
            client = GroqTranscriptionClient()

        with pytest.raises(NotImplementedError, match="Medical"):
            client.process_audio(
                "/tmp/does-not-need-to-exist.wav",
                config=TranscriptionConfig(
                    transcription_type=TranscriptionType.MEDICAL
                ),
            )


class TestFactoryGroq:
    @pytest.fixture(autouse=True)
    def reset_singletons(self):
        import app.services.transcription.factory as factory_mod

        factory_mod._gpu_client = None
        factory_mod._groq_client = None
        factory_mod._deepgram_client = None
        yield
        factory_mod._gpu_client = None
        factory_mod._groq_client = None
        factory_mod._deepgram_client = None

    def test_missing_key_raises_via_factory(self):
        with patch("app.services.transcription.factory.settings") as mock_settings:
            mock_settings.TRANSCRIPTION_BACKEND = TranscriptionBackend.GROQ
            mock_settings.GROQ_API_KEY = ""
            from app.services.transcription.factory import get_provider

            with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
                get_provider()

    def test_returns_groq_client_when_configured(self):
        with patch("app.services.transcription.factory.settings") as mock_settings:
            mock_settings.TRANSCRIPTION_BACKEND = TranscriptionBackend.GROQ
            mock_settings.GROQ_API_KEY = "gsk_test"
            from app.services.transcription.factory import get_provider

            # Avoid constructing a real httpx client against live settings
            with patch(
                "app.services.transcription.groq_client.GroqTranscriptionClient"
            ) as mock_cls:
                mock_cls.return_value = object()
                provider = get_provider()
                assert provider is mock_cls.return_value

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
"""Unit tests for DeepgramTranscriptionClient response parsing and factory wiring."""

import pytest
from unittest.mock import patch

from app.models import TranscriptionBackend, TranscriptionType
from app.services.transcription.deepgram_client import DeepgramTranscriptionClient
from app.services.transcription.types import TranscriptionConfig


SAMPLE_PAYLOAD = {
    "metadata": {"duration": 7.5},
    "results": {
        "channels": [
            {
                "detected_language": "en-US",
                "alternatives": [
                    {
                        "transcript": "Hello world. How are you?",
                        "confidence": 0.98,
                        "detected_language": "en",
                        "words": [
                            {
                                "word": "Hello",
                                "punctuated_word": "Hello",
                                "start": 0.0,
                                "end": 0.6,
                                "confidence": 0.99,
                                "speaker": 0,
                            },
                            {
                                "word": "world.",
                                "punctuated_word": "world.",
                                "start": 0.7,
                                "end": 1.4,
                                "confidence": 0.97,
                                "speaker": 0,
                            },
                            {
                                "word": "How",
                                "punctuated_word": "How",
                                "start": 2.5,
                                "end": 2.9,
                                "confidence": 0.96,
                                "speaker": 1,
                            },
                            {
                                "word": "are",
                                "punctuated_word": "are",
                                "start": 3.0,
                                "end": 3.3,
                                "confidence": 0.95,
                                "speaker": 1,
                            },
                            {
                                "word": "you?",
                                "punctuated_word": "you?",
                                "start": 3.4,
                                "end": 3.9,
                                "confidence": 0.94,
                                "speaker": 1,
                            },
                        ],
                    }
                ],
            }
        ],
        "utterances": [
            {
                "start": 0.0,
                "end": 1.4,
                "confidence": 0.98,
                "channel": 0,
                "transcript": "Hello world.",
                "speaker": 0,
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.6, "speaker": 0},
                    {"word": "world.", "start": 0.7, "end": 1.4, "speaker": 0},
                ],
            },
            {
                "start": 2.5,
                "end": 3.9,
                "confidence": 0.97,
                "channel": 0,
                "transcript": "How are you?",
                "speaker": 1,
                "words": [
                    {"word": "How", "start": 2.5, "end": 2.9, "speaker": 1},
                    {"word": "are", "start": 3.0, "end": 3.3, "speaker": 1},
                    {"word": "you?", "start": 3.4, "end": 3.9, "speaker": 1},
                ],
            },
        ],
    },
}


class TestDeepgramParseResponse:
    def test_maps_utterances_to_segments_with_speakers(self):
        result = DeepgramTranscriptionClient._parse_response(SAMPLE_PAYLOAD)

        assert result.provider_name == "deepgram"
        assert result.language == "en"
        assert result.audio_duration_seconds == 7.5
        assert result.estimated_cost > 0
        assert len(result.segments) == 2

        first = result.segments[0]
        assert first.text == "Hello world."
        assert first.speaker == "SPEAKER_00"
        assert len(first.words) == 2
        assert first.words[0].speaker_label == "SPEAKER_00"

        second = result.segments[1]
        assert second.text == "How are you?"
        assert second.speaker == "SPEAKER_01"
        assert len(second.words) == 3

        assert result.text == "Hello world. How are you?"

    def test_falls_back_to_word_runs_without_utterances(self):
        payload = dict(SAMPLE_PAYLOAD)
        payload["results"] = dict(SAMPLE_PAYLOAD["results"])
        payload["results"].pop("utterances")

        result = DeepgramTranscriptionClient._parse_response(payload)

        assert len(result.segments) == 2
        assert result.segments[0].speaker == "SPEAKER_00"
        assert result.segments[1].speaker == "SPEAKER_01"
        assert result.segments[0].text == "Hello world."
        assert result.segments[1].text == "How are you?"

    def test_empty_payload_returns_empty_result(self):
        result = DeepgramTranscriptionClient._parse_response({})

        assert result.text == ""
        assert result.segments == []
        assert result.language == "en"
        assert result.audio_duration_seconds == 0.0
        assert result.estimated_cost == 0.0

    def test_normalizes_bcp47_detected_language(self):
        payload = {
            "results": {
                "channels": [
                    {
                        "detected_language": "en-US",
                        "alternatives": [{"transcript": "Hi", "words": []}],
                    }
                ]
            }
        }
        result = DeepgramTranscriptionClient._parse_response(payload)
        assert result.language == "en"


class TestDeepgramRequestParams:
    @pytest.fixture
    def client(self):
        with patch("app.services.transcription.deepgram_client.settings") as mock_settings:
            mock_settings.DEEPGRAM_API_KEY = "dg_test"
            mock_settings.DEEPGRAM_BASE_URL = "https://api.deepgram.com"
            mock_settings.DEEPGRAM_MODEL = "nova-3"
            mock_settings.DEEPGRAM_DIARIZE = True
            mock_settings.DEEPGRAM_TIMEOUT = 60
            mock_settings.DEEPGRAM_MAX_FILE_MB = 512
            yield DeepgramTranscriptionClient()

    def test_forced_language_skips_detection(self, client, tmp_path):
        audio = tmp_path / "sample.wav"
        audio.write_bytes(b"RIFF")

        captured = {}

        class FakeResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {}

        def fake_post(url, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

        client._http.post = fake_post
        client._transcribe(str(audio), TranscriptionConfig(language="ur"))

        params = dict(captured["params"])
        assert params["language"] == "ur"
        assert params["detect_language"] == "false"
        assert params["diarize_model"] == "latest"
        assert "diarize" not in params

    def test_auto_detection_uses_allowed_languages(self, client, tmp_path):
        audio = tmp_path / "sample.wav"
        audio.write_bytes(b"RIFF")

        captured = {}

        class FakeResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {}

        def fake_post(url, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

        client._http.post = fake_post
        client._transcribe(
            str(audio),
            TranscriptionConfig(allowed_languages={"ur", "en"}),
        )

        detect_values = [value for key, value in captured["params"] if key == "detect_language"]
        assert detect_values == ["en"]  # "ur" is not a Deepgram detect_language code
        assert not any(key == "language" for key, _ in captured["params"])

    def test_unsupported_only_allowed_languages_forces_fallback(self, client, tmp_path):
        audio = tmp_path / "sample.wav"
        audio.write_bytes(b"RIFF")

        captured = {}

        class FakeResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {}

        def fake_post(url, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

        client._http.post = fake_post
        client._transcribe(str(audio), TranscriptionConfig(allowed_languages={"ur"}))

        params = dict(captured["params"])
        # "ur" cannot be auto-detected by Deepgram; force it rather than
        # detect_language=true which could return a language outside the set.
        assert params["language"] == "ur"
        assert params["detect_language"] == "false"


class TestDeepgramClientInit:
    def test_missing_api_key_raises(self):
        with patch("app.services.transcription.deepgram_client.settings") as mock_settings:
            mock_settings.DEEPGRAM_API_KEY = ""
            with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
                DeepgramTranscriptionClient()

    def test_medical_mode_rejected(self):
        with patch("app.services.transcription.deepgram_client.settings") as mock_settings:
            mock_settings.DEEPGRAM_API_KEY = "dg_test"
            mock_settings.DEEPGRAM_BASE_URL = "https://api.deepgram.com"
            mock_settings.DEEPGRAM_MODEL = "nova-3"
            mock_settings.DEEPGRAM_DIARIZE = True
            mock_settings.DEEPGRAM_TIMEOUT = 60
            mock_settings.DEEPGRAM_MAX_FILE_MB = 512
            client = DeepgramTranscriptionClient()

        with pytest.raises(NotImplementedError, match="Medical"):
            client.process_audio(
                "/tmp/does-not-need-to-exist.wav",
                config=TranscriptionConfig(transcription_type=TranscriptionType.MEDICAL),
            )


class TestFactoryDeepgram:
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
            mock_settings.TRANSCRIPTION_BACKEND = TranscriptionBackend.DEEPGRAM
            mock_settings.DEEPGRAM_API_KEY = ""
            from app.services.transcription.factory import get_provider

            with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
                get_provider()

    def test_returns_deepgram_client_when_configured(self):
        with patch("app.services.transcription.factory.settings") as mock_settings:
            mock_settings.TRANSCRIPTION_BACKEND = TranscriptionBackend.DEEPGRAM
            mock_settings.DEEPGRAM_API_KEY = "dg_test"
            from app.services.transcription.factory import get_provider

            with patch(
                "app.services.transcription.deepgram_client.DeepgramTranscriptionClient"
            ) as mock_cls:
                mock_cls.return_value = object()
                provider = get_provider()
                assert provider is mock_cls.return_value

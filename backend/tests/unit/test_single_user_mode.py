# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
"""Unit tests for single-user (no-login) mode.

Run with: ``uv run pytest tests/unit/test_single_user_mode.py --noconftest``
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.security import verify_supabase_jwt


class TestSingleUserFlag:
    def test_default_is_false(self):
        default = Settings.model_fields["SINGLE_USER_MODE"].default
        assert default is False, (
            f"SINGLE_USER_MODE default regressed: {default!r}. "
            "It must default to False (multi-user/Supabase auth)."
        )


class TestVerifySupabaseJwtSingleUser:
    def test_single_user_mode_returns_fixed_identity_without_token(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.SINGLE_USER_MODE = True
            # credentials=None — no Authorization header at all
            payload = verify_supabase_jwt(credentials=None)

        assert payload["sub"] == "single-user-local"
        assert payload["email"] == "local@zabt.local"
        assert payload["user_metadata"]["full_name"] == "Local User"

    def test_single_user_mode_ignores_bad_token(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.SINGLE_USER_MODE = True

            class FakeCreds:
                credentials = "not-a-real-jwt"

            payload = verify_supabase_jwt(credentials=FakeCreds())

        assert payload["sub"] == "single-user-local"

    def test_multi_user_mode_rejects_missing_token(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.SINGLE_USER_MODE = False
            mock_settings.SUPABASE_URL = "https://example.supabase.co"
            mock_settings.SUPABASE_ANON_KEY = "anon"
            mock_settings.SUPABASE_JWT_SECRET = "secret"

            with pytest.raises(HTTPException) as exc_info:
                verify_supabase_jwt(credentials=None)

        assert exc_info.value.status_code == 401

    def test_multi_user_mode_rejects_garbage_token(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.SINGLE_USER_MODE = False
            mock_settings.SUPABASE_URL = "https://example.supabase.co"
            mock_settings.SUPABASE_ANON_KEY = "anon"
            mock_settings.SUPABASE_JWT_SECRET = "secret"

            class FakeCreds:
                credentials = "garbage.token.here"

            # Force JWKS path to fail with a non-HTTP error so code falls through
            # to the HS256 fallback (which also fails) → 401.
            with patch(
                "app.core.security._get_jwks",
                side_effect=Exception("jwks unreachable"),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    verify_supabase_jwt(credentials=FakeCreds())

        assert exc_info.value.status_code == 401

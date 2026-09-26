// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2025-2026 Afeef Janjua
/**
 * Single-user / no-login mode.
 *
 * When true the app skips Supabase entirely: no login redirect, no JWT
 * attachment, no logout. Backend must also run with SINGLE_USER_MODE=true.
 * Read at build time via NEXT_PUBLIC_SINGLE_USER_MODE.
 */
const hasSupabaseConfig = Boolean(
  process.env.NEXT_PUBLIC_SUPABASE_URL?.trim() &&
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim()
);

export const isSingleUserMode =
  process.env.NEXT_PUBLIC_SINGLE_USER_MODE === "true" || !hasSupabaseConfig;

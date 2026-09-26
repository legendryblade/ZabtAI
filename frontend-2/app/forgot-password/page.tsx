// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2025-2026 Afeef Janjua
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isSingleUserMode } from "@/app/lib/auth-mode";

export default function ForgotPasswordPage() {
  const router = useRouter();

  // Single-user mode: no passwords — go straight to the app.
  useEffect(() => {
    if (isSingleUserMode) {
      router.replace("/");
    }
  }, [router]);

  if (isSingleUserMode) {
    return null;
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-stone-50 px-4">
      <div className="w-full max-w-sm bg-white rounded-lg border border-stone-200 p-8">
        <h1 className="text-xl font-semibold text-stone-800">
          Reset your password
        </h1>
        <p className="text-sm text-stone-500 mt-2">
          Password reset is coming soon.
        </p>
        <Link
          href="/login"
          className="inline-block mt-6 text-sm text-primary hover:underline"
        >
          ← Back to sign in
        </Link>
      </div>
    </main>
  );
}

/**
 * Onboarding API client — wraps /api/onboarding/* with typed helpers.
 */

import type { OnboardingProgress, OnboardingStatus } from "./types";

const BASE = "/api/onboarding";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`Onboarding API ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchProgress(): Promise<OnboardingProgress> {
  const res = await fetch(`${BASE}/progress`, { credentials: "include" });
  const data = await jsonOrThrow<{ progress: OnboardingProgress }>(res);
  return data.progress;
}

export interface UpdateProgressBody {
  current_step?: string;
  mark_completed?: string[];
  mark_skipped?: string[];
  status?: OnboardingStatus;
  banner_dismissed?: boolean;
}

export async function patchProgress(
  body: UpdateProgressBody,
): Promise<OnboardingProgress> {
  const res = await fetch(`${BASE}/progress`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await jsonOrThrow<{ progress: OnboardingProgress }>(res);
  return data.progress;
}

export async function replayTour(): Promise<OnboardingProgress> {
  const res = await fetch(`${BASE}/replay`, {
    method: "POST",
    credentials: "include",
  });
  const data = await jsonOrThrow<{ progress: OnboardingProgress }>(res);
  return data.progress;
}

export async function markPageHintSeen(pathname: string): Promise<void> {
  await fetch(`${BASE}/page-hints/seen`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pathname }),
  });
}

export async function resetPageHints(): Promise<void> {
  await fetch(`${BASE}/page-hints/reset`, {
    method: "POST",
    credentials: "include",
  });
}

export async function dismissTour(): Promise<void> {
  await fetch(`${BASE}/dismiss`, {
    method: "POST",
    credentials: "include",
  });
}

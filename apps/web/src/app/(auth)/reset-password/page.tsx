import { Suspense } from "react";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";

export const metadata = {
  title: "Set New Password — Plan2Sprint",
};

// ResetPasswordForm uses ``useSearchParams()`` to read the recovery
// ``code`` query param from the email link. Next.js's App Router
// requires any component that calls useSearchParams during render to
// be wrapped in a Suspense boundary, otherwise the route bails out of
// static generation with the missing-suspense-with-csr-bailout error
// (which is exactly how we found this — the production build refused
// to compile until we added this boundary).
//
// The fallback renders a near-identical loader to the one the form
// itself shows during its on-mount code-exchange phase, so the user
// sees a single continuous "verifying…" beat rather than a flash of
// blank → loader → form.
export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/10" />
          <p className="text-sm text-[var(--text-secondary)]">Loading…</p>
        </div>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}

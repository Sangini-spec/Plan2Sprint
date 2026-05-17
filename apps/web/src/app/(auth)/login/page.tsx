import { Suspense } from "react";
import { LoginForm } from "@/components/auth/login-form";

export const metadata = {
  title: "Sign In - Plan2Sprint",
};

// Hotfix 61 - LoginForm now reads ``?next=`` via useSearchParams() so
// invitees who click an invite link without an active session land back
// on the invite page after auth. Next.js 15 requires that any client
// component reading search params is rendered inside a Suspense
// boundary so static prerendering can fall back to client rendering.
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

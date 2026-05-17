import { Suspense } from "react";
import { SignupForm } from "@/components/auth/signup-form";

export const metadata = {
  title: "Create Account - Plan2Sprint",
};

// Hotfix 65C - SignupForm reads ``?next=`` via useSearchParams() so an
// invitee who hops invite → login → signup still lands back on the
// invite page after auth. Next.js 15 requires that any client component
// reading search params is rendered inside a Suspense boundary so
// static prerendering can fall back to client rendering.
export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <SignupForm />
    </Suspense>
  );
}

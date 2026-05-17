"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2, CheckCircle, XCircle, Building2 } from "lucide-react";
import { Button, Badge } from "@/components/ui";
import { ROLE_LABELS, type UserRole } from "@/lib/types/auth";
import { createClient } from "@/lib/supabase/client";

interface InviteInfo {
  id: string;
  email: string;
  role: string;
  status: string;
  organizationName: string;
  expiresAt: string | null;
}

export default function InviteAcceptPage() {
  const params = useParams();
  const router = useRouter();
  const token = params.token as string;

  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  // ``loadError`` = the GET call that fetches the invitation failed
  //   (bad token, expired, server error). UI shows "Invalid Invitation".
  // ``acceptError`` = the GET succeeded and we showed the card, but the
  //   POST /accept call failed (e.g. user already in another workspace,
  //   or session expired during the click). We keep the card visible so
  //   the user has context, and inline the error under the button.
  const [result, setResult] = useState<"accepted" | "error" | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [acceptError, setAcceptError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`/api/organizations/invitations/${token}`);
        if (res.ok) {
          setInvite(await res.json());
        } else {
          const data = await res.json().catch(() => ({}));
          setErrorMsg(data.detail || "Invitation not found");
          setResult("error");
        }
      } catch {
        setErrorMsg("Unable to load invitation");
        setResult("error");
      }
      setLoading(false);
    })();
  }, [token]);

  // Hotfix 65B - when the loaded invitation is already accepted (most
  // commonly because Hotfix 65A consumed it server-side during signup
  // and the auth callback bounced the user back to ``?next=/invite/...``)
  // silently route through /dashboard. The role-aware middleware
  // takes them to /po, /dev, or /stakeholder. Done in an effect so
  // we're not mutating router state during render.
  useEffect(() => {
    if (invite && invite.status === "accepted") {
      router.replace("/dashboard");
    }
  }, [invite, router]);

  const handleAccept = async () => {
    setAccepting(true);
    setAcceptError("");
    try {
      const res = await fetch(
        `/api/organizations/invitations/${token}/accept`,
        { method: "POST" }
      );
      if (res.ok) {
        setResult("accepted");
        // Hotfix 59: route the new invitee straight to their role's
        // dashboard instead of the marketing landing page. Falls back
        // to /dashboard (which the middleware then routes by role) if
        // we couldn't read the role from the response.
        let landing = "/dashboard";
        try {
          const data = await res.clone().json();
          const role = (data?.role || "").toLowerCase();
          if (role === "developer" || role === "engineering_manager") landing = "/dev";
          else if (role === "stakeholder") landing = "/stakeholder";
          else if (role === "product_owner" || role === "admin" || role === "owner") landing = "/po";
        } catch {
          // body wasn't JSON - leave landing as /dashboard so
          // middleware can role-route from there.
        }
        // Hotfix 70B - force a Supabase session refresh BEFORE
        // navigating so the user's new JWT carries the up-to-date
        // ``user_metadata.role`` that Hotfix 66B just wrote. Without
        // this, the user's existing session token still claims their
        // signup-time role (default ``product_owner``) and the
        // middleware role-routes them to /po even though their
        // Plan2Sprint User row says developer/stakeholder. Best-effort:
        // if the refresh fails (offline, transient Supabase blip), we
        // still navigate - they'll just need to log out + log in
        // manually to pick up the role. The 2s delay below also gives
        // the success card time to render.
        try {
          const supabase = createClient();
          await supabase.auth.refreshSession();
        } catch {
          // ignore - fallback path is "log out + log in"
        }
        setTimeout(() => router.push(landing), 2000);
      } else if (res.status === 401) {
        // Hotfix 61: user clicked Accept without an active session.
        // Punt them to login with a return-URL so they land back here
        // automatically, instead of showing a confusing "Invalid
        // Invitation – Not authenticated" banner.
        const next = encodeURIComponent(`/invite/${token}`);
        router.push(`/login?next=${next}`);
        return;
      } else {
        // Hotfix 61: keep the invitation card visible and surface the
        // server's reason inline under the button, instead of replacing
        // the whole page with the misleading "Invalid Invitation"
        // header. Common reasons: 409 (email already in another org),
        // 400 (invitation already accepted/expired), 500 (server bug).
        const data = await res.json().catch(() => ({}));
        setAcceptError(data.detail || "Failed to accept invitation");
      }
    } catch {
      setAcceptError("Something went wrong. Please try again.");
    }
    setAccepting(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  if (result === "accepted") {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
        <CheckCircle className="h-12 w-12 text-[var(--color-rag-green)]" />
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          You&apos;re in!
        </h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Redirecting to your dashboard...
        </p>
      </div>
    );
  }

  if (result === "error" || !invite) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
        <XCircle className="h-12 w-12 text-[var(--color-rag-red)]" />
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          Invalid Invitation
        </h1>
        <p className="text-sm text-[var(--text-secondary)] max-w-sm">
          {errorMsg || "This invitation link is invalid or has expired."}
        </p>
        <Button variant="secondary" size="md" onClick={() => router.push("/login")}>
          Go to Login
        </Button>
      </div>
    );
  }

  if (invite.status !== "pending") {
    // Hotfix 65B - for an already-accepted invitation, show a
    // brief loading spinner while the redirect-to-/dashboard effect
    // above kicks the user to the right place. Other terminal states
    // (expired / revoked) keep the explanatory dead-end UI.
    if (invite.status === "accepted") {
      return (
        <div className="flex items-center justify-center min-h-[60vh]">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--text-secondary)]" />
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
        <XCircle className="h-12 w-12 text-[var(--text-secondary)]" />
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          Invitation {invite.status}
        </h1>
        <p className="text-sm text-[var(--text-secondary)]">
          This invitation has already been {invite.status}.
        </p>
        <Button variant="secondary" size="md" onClick={() => router.push("/login")}>
          Go to Login
        </Button>
      </div>
    );
  }

  const roleLabel = ROLE_LABELS[invite.role as UserRole] || invite.role;

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 px-4">
      <div className="w-full max-w-sm rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] shadow-lg p-8 text-center space-y-5">
        <div className="flex justify-center">
          <div className="h-14 w-14 rounded-xl bg-[var(--color-brand-secondary)]/10 flex items-center justify-center">
            <Building2 className="h-7 w-7 text-[var(--color-brand-secondary)]" />
          </div>
        </div>

        <div>
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">
            Join {invite.organizationName}
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            You&apos;ve been invited to join as
          </p>
          <Badge variant="brand" className="mt-2">
            {roleLabel}
          </Badge>
        </div>

        <p className="text-xs text-[var(--text-secondary)]">
          Invited: {invite.email}
        </p>

        <div className="flex flex-col gap-2">
          <Button
            variant="primary"
            size="md"
            onClick={handleAccept}
            disabled={accepting}
            className="w-full"
          >
            {accepting && <Loader2 className="h-4 w-4 animate-spin" />}
            {accepting ? "Joining..." : "Accept Invitation"}
          </Button>
          {acceptError && (
            <div
              role="alert"
              className="text-xs text-left rounded-md border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5 text-[var(--color-rag-red)] px-3 py-2"
            >
              {acceptError}
            </div>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push("/login")}
            className="w-full"
          >
            Decline
          </Button>
        </div>
      </div>
    </div>
  );
}

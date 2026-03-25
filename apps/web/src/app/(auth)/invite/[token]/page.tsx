"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2, CheckCircle, XCircle, Building2 } from "lucide-react";
import { Button, Badge } from "@/components/ui";
import { ROLE_LABELS, type UserRole } from "@/lib/types/auth";

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
  const [result, setResult] = useState<"accepted" | "error" | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

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

  const handleAccept = async () => {
    setAccepting(true);
    try {
      const res = await fetch(
        `/api/organizations/invitations/${token}/accept`,
        { method: "POST" }
      );
      if (res.ok) {
        setResult("accepted");
        setTimeout(() => router.push("/"), 2000);
      } else {
        const data = await res.json().catch(() => ({}));
        setErrorMsg(data.detail || "Failed to accept invitation");
        setResult("error");
      }
    } catch {
      setErrorMsg("Something went wrong");
      setResult("error");
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

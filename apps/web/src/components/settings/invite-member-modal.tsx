"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Copy, Check, Mail, Loader2 } from "lucide-react";
import { Button, Input, Select, FormField } from "@/components/ui";
import { ROLE_LABELS, type UserRole } from "@/lib/types/auth";

const INVITE_ROLES: { value: UserRole; label: string }[] = [
  { value: "product_owner", label: "Product Owner" },
  { value: "developer", label: "Developer" },
  { value: "stakeholder", label: "Stakeholder" },
];

interface InviteMemberModalProps {
  open: boolean;
  onClose: () => void;
  onInvited: () => void;
}

export function InviteMemberModal({
  open,
  onClose,
  onInvited,
}: InviteMemberModalProps) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("developer");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    inviteUrl: string;
    emailSent: boolean;
  } | null>(null);
  const [copied, setCopied] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const res = await fetch("/api/organizations/current/invitations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), role }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to create invitation");
      }

      const data = await res.json();
      setResult({ inviteUrl: data.inviteUrl, emailSent: data.emailSent });
      onInvited();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (!result?.inviteUrl) return;
    await navigator.clipboard.writeText(result.inviteUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleClose = () => {
    setEmail("");
    setRole("developer");
    setError(null);
    setResult(null);
    setCopied(false);
    onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={handleClose}
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.15 }}
            className="relative w-full max-w-md mx-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] shadow-xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                Invite Team Member
              </h2>
              <button
                onClick={handleClose}
                className="p-1 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Body */}
            <div className="px-6 py-5">
              {!result ? (
                <form onSubmit={handleSubmit} className="space-y-4">
                  <FormField label="Email Address" required>
                    <Input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="colleague@company.com"
                      autoFocus
                    />
                  </FormField>

                  <FormField label="Role">
                    <Select
                      value={role}
                      onChange={(e) => setRole(e.target.value as UserRole)}
                    >
                      {INVITE_ROLES.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                    </Select>
                  </FormField>

                  {error && (
                    <p className="text-xs text-[var(--color-rag-red)]">
                      {error}
                    </p>
                  )}

                  <div className="flex justify-end gap-2 pt-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      type="button"
                      onClick={handleClose}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      type="submit"
                      disabled={loading || !email.trim()}
                    >
                      {loading ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Mail className="h-3.5 w-3.5" />
                      )}
                      {loading ? "Sending..." : "Send Invite"}
                    </Button>
                  </div>
                </form>
              ) : (
                <div className="space-y-4">
                  {result.emailSent ? (
                    <div className="flex items-start gap-3 p-3 rounded-lg bg-[var(--color-rag-green)]/5 border border-[var(--color-rag-green)]/20">
                      <Check className="h-4 w-4 mt-0.5 text-[var(--color-rag-green)]" />
                      <div>
                        <p className="text-sm font-medium text-[var(--text-primary)]">
                          Invitation email sent
                        </p>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                          An invite email has been sent to {email}.
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3 p-3 rounded-lg bg-[var(--color-rag-amber)]/5 border border-[var(--color-rag-amber)]/20">
                      <Mail className="h-4 w-4 mt-0.5 text-[var(--color-rag-amber)]" />
                      <div>
                        <p className="text-sm font-medium text-[var(--text-primary)]">
                          Invitation created
                        </p>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                          Email service unavailable. Share the link below manually.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Copy link section */}
                  <div>
                    <label className="text-xs font-medium text-[var(--text-secondary)] mb-1.5 block">
                      Invite Link
                    </label>
                    <div className="flex gap-2">
                      <Input
                        value={result.inviteUrl}
                        readOnly
                        className="text-xs font-mono"
                      />
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={handleCopy}
                        className="shrink-0"
                      >
                        {copied ? (
                          <Check className="h-3.5 w-3.5 text-[var(--color-rag-green)]" />
                        ) : (
                          <Copy className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </div>
                  </div>

                  <div className="flex justify-end pt-2">
                    <Button variant="primary" size="sm" onClick={handleClose}>
                      Done
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

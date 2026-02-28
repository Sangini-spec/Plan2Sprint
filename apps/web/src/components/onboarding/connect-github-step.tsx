"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight,
  ArrowLeft,
  Github,
  CheckCircle2,
  Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";

/* ------------------------------------------------------------------ */
/*  Mock repos                                                         */
/* ------------------------------------------------------------------ */

const MOCK_REPOS = [
  { id: "checkout", name: "acme/checkout-service" },
  { id: "gateway", name: "acme/api-gateway" },
  { id: "mobile", name: "acme/mobile-app" },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function ConnectGithubStep({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const [connected, setConnected] = useState(false);
  const [selectedRepos, setSelectedRepos] = useState<string[]>([]);

  const toggleRepo = (id: string) => {
    setSelectedRepos((prev) =>
      prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]
    );
  };

  return (
    <div className="flex flex-col items-center text-center">
      {/* Header */}
      <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--bg-surface-raised)]">
        <Github className="h-6 w-6 text-[var(--text-primary)]" />
      </div>

      <h2 className="mt-4 text-2xl font-bold text-[var(--text-primary)]">
        Connect GitHub
      </h2>
      <p className="mt-2 max-w-lg text-sm text-[var(--text-secondary)]">
        Install the Plan2Sprint GitHub App to enable PR monitoring, CI tracking,
        and commit analysis.
      </p>

      {/* GitHub App Card */}
      <div className="mt-8 w-full max-w-md">
        <div
          className={cn(
            "rounded-2xl border p-6 transition-all duration-300",
            "bg-[var(--bg-surface)]",
            connected
              ? "border-[var(--color-rag-green)]/40"
              : "border-[var(--border-subtle)]"
          )}
        >
          {/* App header */}
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--bg-surface-raised)]">
              <Github className="h-5 w-5 text-[var(--text-primary)]" />
            </div>
            <div className="text-left">
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                Plan2Sprint GitHub App
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                github.com/apps/plan2sprint
              </p>
            </div>
          </div>

          {/* Install / Connected */}
          <AnimatePresence mode="wait">
            {!connected ? (
              <motion.div
                key="install"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="mt-5"
              >
                <Button
                  size="md"
                  className="w-full"
                  onClick={() => setConnected(true)}
                >
                  <Github className="h-4 w-4" />
                  Install GitHub App
                </Button>
              </motion.div>
            ) : (
              <motion.div
                key="connected"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="mt-5"
              >
                {/* Success */}
                <div className="flex items-center gap-2 text-left">
                  <CheckCircle2 className="h-5 w-5 text-[var(--color-rag-green)]" />
                  <span className="text-sm font-medium text-[var(--color-rag-green)]">
                    Connected to acme-org
                  </span>
                </div>

                {/* Repo selection */}
                <div className="mt-4 space-y-2">
                  <p className="text-left text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Select repositories
                  </p>
                  {MOCK_REPOS.map((repo) => {
                    const isChecked = selectedRepos.includes(repo.id);
                    return (
                      <button
                        key={repo.id}
                        type="button"
                        onClick={() => toggleRepo(repo.id)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all duration-200 cursor-pointer",
                          isChecked
                            ? "border-[var(--color-brand-secondary)]/40 bg-[var(--color-brand-secondary)]/5"
                            : "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] hover:border-[var(--color-brand-secondary)]/20"
                        )}
                      >
                        {/* Checkbox */}
                        <div
                          className={cn(
                            "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-all duration-200",
                            isChecked
                              ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]"
                              : "border-[var(--border-subtle)]"
                          )}
                        >
                          {isChecked && (
                            <Check className="h-3 w-3 text-white" />
                          )}
                        </div>
                        <span className="text-sm font-medium text-[var(--text-primary)] font-mono">
                          {repo.name}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Navigation */}
      <div className="mt-10 flex items-center gap-3">
        <Button variant="secondary" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <Button
          disabled={!connected || selectedRepos.length === 0}
          onClick={onNext}
        >
          Continue
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

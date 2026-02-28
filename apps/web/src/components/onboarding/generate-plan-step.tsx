"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight,
  ArrowLeft,
  Sparkles,
  Loader2,
  CheckCircle2,
  Users,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Badge } from "@/components/ui";

/* ------------------------------------------------------------------ */
/*  Generation steps                                                   */
/* ------------------------------------------------------------------ */

const GENERATION_STEPS = [
  { label: "Analyzing backlog...", delay: 800 },
  { label: "Calculating team velocity...", delay: 800 },
  { label: "Optimizing assignments...", delay: 800 },
  { label: "Plan generated!", delay: 0 },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function GeneratePlanStep({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const [generating, setGenerating] = useState(false);
  const [currentGenStep, setCurrentGenStep] = useState(-1);
  const [complete, setComplete] = useState(false);

  const startGeneration = useCallback(() => {
    setGenerating(true);
    setCurrentGenStep(0);
  }, []);

  /* Drive the mock generation sequence via useEffect */
  useEffect(() => {
    if (!generating || currentGenStep < 0) return;

    // If we've reached the last step, mark complete
    if (currentGenStep >= GENERATION_STEPS.length - 1) {
      setGenerating(false);
      setComplete(true);
      return;
    }

    const timeout = setTimeout(() => {
      setCurrentGenStep((s) => s + 1);
    }, GENERATION_STEPS[currentGenStep].delay);

    return () => clearTimeout(timeout);
  }, [generating, currentGenStep]);

  return (
    <div className="flex flex-col items-center text-center">
      {/* Header */}
      <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--color-brand-secondary)]/10">
        <Sparkles className="h-6 w-6 text-[var(--color-brand-secondary)]" />
      </div>

      <h2 className="mt-4 text-2xl font-bold text-[var(--text-primary)]">
        Generate Your First AI Sprint Plan
      </h2>
      <p className="mt-2 max-w-lg text-sm text-[var(--text-secondary)]">
        Plan2Sprint will analyze your backlog, team velocity, and capacity to
        generate an optimized sprint plan.
      </p>

      {/* Main content area */}
      <div className="mt-8 w-full max-w-md">
        <AnimatePresence mode="wait">
          {/* Initial state: Generate button */}
          {!generating && !complete && (
            <motion.div
              key="idle"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
            >
              <Button size="lg" className="w-full" onClick={startGeneration}>
                <Sparkles className="h-5 w-5" />
                Generate Sprint Plan
              </Button>
            </motion.div>
          )}

          {/* Generating state: step indicators */}
          {generating && (
            <motion.div
              key="generating"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-6"
            >
              <div className="space-y-4">
                {GENERATION_STEPS.map((step, idx) => {
                  const isActive = idx === currentGenStep;
                  const isDone = idx < currentGenStep;
                  const isPending = idx > currentGenStep;

                  return (
                    <div
                      key={idx}
                      className={cn(
                        "flex items-center gap-3 transition-opacity duration-300",
                        isPending && "opacity-30"
                      )}
                    >
                      {isDone ? (
                        <CheckCircle2 className="h-5 w-5 shrink-0 text-[var(--color-rag-green)]" />
                      ) : isActive ? (
                        <Loader2 className="h-5 w-5 shrink-0 animate-spin text-[var(--color-brand-secondary)]" />
                      ) : (
                        <div className="h-5 w-5 shrink-0 rounded-full border-2 border-[var(--border-subtle)]" />
                      )}
                      <span
                        className={cn(
                          "text-sm font-medium",
                          isActive
                            ? "text-[var(--text-primary)]"
                            : isDone
                              ? "text-[var(--color-rag-green)]"
                              : "text-[var(--text-secondary)]"
                        )}
                      >
                        {step.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </motion.div>
          )}

          {/* Complete state: plan summary */}
          {complete && (
            <motion.div
              key="complete"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="rounded-2xl border border-[var(--color-rag-green)]/30 bg-[var(--bg-surface)] p-6"
            >
              {/* Success banner */}
              <div className="flex items-center justify-center gap-2 mb-5">
                <CheckCircle2 className="h-5 w-5 text-[var(--color-rag-green)]" />
                <span className="text-sm font-semibold text-[var(--color-rag-green)]">
                  Sprint plan generated successfully
                </span>
              </div>

              {/* Plan summary grid */}
              <div className="grid grid-cols-2 gap-4">
                <div className="flex items-center gap-3 rounded-xl bg-[var(--bg-surface-raised)] p-4">
                  <Target className="h-5 w-5 text-[var(--color-brand-secondary)]" />
                  <div className="text-left">
                    <p className="text-xs text-[var(--text-secondary)]">
                      Sprint
                    </p>
                    <p className="text-lg font-bold text-[var(--text-primary)]">
                      24
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 rounded-xl bg-[var(--bg-surface-raised)] p-4">
                  <Zap className="h-5 w-5 text-[var(--color-brand-accent)]" />
                  <div className="text-left">
                    <p className="text-xs text-[var(--text-secondary)]">
                      Story Points
                    </p>
                    <p className="text-lg font-bold text-[var(--text-primary)]">
                      58 SP
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 rounded-xl bg-[var(--bg-surface-raised)] p-4">
                  <TrendingUp className="h-5 w-5 text-[var(--color-rag-green)]" />
                  <div className="text-left">
                    <p className="text-xs text-[var(--text-secondary)]">
                      Confidence
                    </p>
                    <p className="text-lg font-bold text-[var(--text-primary)]">
                      84%
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 rounded-xl bg-[var(--bg-surface-raised)] p-4">
                  <Users className="h-5 w-5 text-[var(--color-brand-secondary)]" />
                  <div className="text-left">
                    <p className="text-xs text-[var(--text-secondary)]">
                      Developers
                    </p>
                    <p className="text-lg font-bold text-[var(--text-primary)]">
                      6
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-4 flex justify-center">
                <Badge variant="rag-green">Optimized for team capacity</Badge>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Navigation */}
      <div className="mt-10 flex items-center gap-3">
        <Button variant="secondary" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <Button disabled={!complete} onClick={onNext}>
          Continue
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

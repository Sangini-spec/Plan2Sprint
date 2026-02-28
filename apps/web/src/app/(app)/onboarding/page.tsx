"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Rocket } from "lucide-react";
import { cn } from "@/lib/utils";

import { ConnectToolStep } from "@/components/onboarding/connect-tool-step";
import { ConnectGithubStep } from "@/components/onboarding/connect-github-step";
import { ConfigureCommsStep } from "@/components/onboarding/configure-comms-step";
import { GeneratePlanStep } from "@/components/onboarding/generate-plan-step";
import { SetStandupTimeStep } from "@/components/onboarding/set-standup-time-step";

/* ------------------------------------------------------------------ */
/*  Step metadata                                                      */
/* ------------------------------------------------------------------ */

const STEPS = [
  { label: "Project Tool" },
  { label: "GitHub" },
  { label: "Comms" },
  { label: "Sprint Plan" },
  { label: "Standup" },
] as const;

/* ------------------------------------------------------------------ */
/*  Slide animation variants                                           */
/* ------------------------------------------------------------------ */

const slideVariants = {
  enter: (direction: number) => ({
    x: direction > 0 ? 300 : -300,
    opacity: 0,
  }),
  center: {
    x: 0,
    opacity: 1,
  },
  exit: (direction: number) => ({
    x: direction > 0 ? -300 : 300,
    opacity: 0,
  }),
};

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function OnboardingPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [direction, setDirection] = useState(1);
  const [finished, setFinished] = useState(false);

  const goNext = useCallback(() => {
    setDirection(1);
    setCurrentStep((s) => Math.min(s + 1, STEPS.length - 1));
  }, []);

  const goBack = useCallback(() => {
    setDirection(-1);
    setCurrentStep((s) => Math.max(s - 1, 0));
  }, []);

  const handleFinish = useCallback(() => {
    setFinished(true);
    setTimeout(() => {
      router.push("/dashboard");
    }, 2000);
  }, [router]);

  /* ---------------------------------------------------------------- */
  /*  Finished state                                                   */
  /* ---------------------------------------------------------------- */

  if (finished) {
    return (
      <div className="flex min-h-[80vh] flex-col items-center justify-center text-center">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 260, damping: 20 }}
          className="flex flex-col items-center"
        >
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[var(--color-rag-green)]/10">
            <CheckCircle2 className="h-8 w-8 text-[var(--color-rag-green)]" />
          </div>
          <h2 className="mt-6 text-2xl font-bold text-[var(--text-primary)]">
            You&apos;re All Set!
          </h2>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            Redirecting you to the dashboard...
          </p>
          <div className="mt-4 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <Rocket className="h-4 w-4 text-[var(--color-brand-secondary)]" />
            <span>Plan2Sprint is ready to go</span>
          </div>
        </motion.div>
      </div>
    );
  }

  /* ---------------------------------------------------------------- */
  /*  Wizard                                                           */
  /* ---------------------------------------------------------------- */

  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center py-8">
      {/* ----------------------------------------------------------- */}
      {/*  Progress indicator                                          */}
      {/* ----------------------------------------------------------- */}
      <nav className="mb-12 w-full max-w-xl">
        <div className="flex items-center justify-between">
          {STEPS.map((step, idx) => {
            const isCompleted = idx < currentStep;
            const isActive = idx === currentStep;

            return (
              <div key={idx} className="flex flex-1 items-center">
                {/* Dot + label */}
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition-all duration-300",
                      isCompleted
                        ? "bg-[var(--color-brand-secondary)] text-white"
                        : isActive
                          ? "border-2 border-[var(--color-brand-secondary)] text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/10"
                          : "border-2 border-[var(--border-subtle)] text-[var(--text-secondary)]"
                    )}
                  >
                    {isCompleted ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      idx + 1
                    )}
                  </div>
                  <span
                    className={cn(
                      "mt-2 text-[11px] font-medium whitespace-nowrap transition-colors duration-200",
                      isActive
                        ? "text-[var(--color-brand-secondary)]"
                        : isCompleted
                          ? "text-[var(--text-primary)]"
                          : "text-[var(--text-secondary)]"
                    )}
                  >
                    {step.label}
                  </span>
                </div>

                {/* Connector line */}
                {idx < STEPS.length - 1 && (
                  <div className="mx-2 mt-[-18px] h-0.5 flex-1 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                    <motion.div
                      className="h-full bg-[var(--color-brand-secondary)]"
                      initial={{ width: "0%" }}
                      animate={{
                        width: isCompleted ? "100%" : "0%",
                      }}
                      transition={{ duration: 0.4, ease: "easeInOut" }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>

      {/* ----------------------------------------------------------- */}
      {/*  Step content with slide transitions                         */}
      {/* ----------------------------------------------------------- */}
      <div className="relative w-full overflow-hidden">
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={currentStep}
            custom={direction}
            variants={slideVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] }}
            className="w-full"
          >
            {currentStep === 0 && <ConnectToolStep onNext={goNext} />}
            {currentStep === 1 && (
              <ConnectGithubStep onNext={goNext} onBack={goBack} />
            )}
            {currentStep === 2 && (
              <ConfigureCommsStep onNext={goNext} onBack={goBack} />
            )}
            {currentStep === 3 && (
              <GeneratePlanStep onNext={goNext} onBack={goBack} />
            )}
            {currentStep === 4 && (
              <SetStandupTimeStep onFinish={handleFinish} onBack={goBack} />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

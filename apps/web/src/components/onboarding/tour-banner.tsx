"use client";

/**
 * TourBanner — INLINE banner inserted between the topbar and the main
 * content area. Takes its own height in the document flow so the
 * dashboard naturally shifts down, and shifts back up when the tour
 * ends. No overlay, no overlap.
 *
 * Mounted directly in (app)/layout.tsx (NOT inside OnboardingTour)
 * so it participates in the flex column with AppTopbar + main.
 *
 * The accompanying anchor-element outline is a separate component
 * (AnchorOutline) which stays fixed-positioned so it follows the
 * highlighted UI element as the user scrolls.
 */

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, X, Sparkles } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

interface Rect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

/** Single-selector outline. Used internally by AnchorOutline to render
 *  one ring per selector — multi-anchor support comes from wrapping
 *  this in a list. */
function SingleAnchorOutline({ selector }: { selector: string }) {
  const [rect, setRect] = useState<Rect | null>(null);

  useEffect(() => {
    if (!selector) {
      setRect(null);
      return;
    }
    let raf: number | null = null;
    let retries = 0;
    const MAX_RETRIES = 40;

    function measure() {
      const el = document.querySelector(selector) as HTMLElement | null;
      if (!el) {
        if (retries++ < MAX_RETRIES) {
          raf = requestAnimationFrame(measure);
        } else {
          setRect(null);
        }
        return;
      }
      const r = el.getBoundingClientRect();
      setRect({
        top: r.top,
        left: r.left,
        right: r.right,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      });
      if (r.bottom < 0 || r.top > window.innerHeight) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
    raf = requestAnimationFrame(measure);

    const onChange = () => {
      const el = document.querySelector(selector) as HTMLElement | null;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setRect({
        top: r.top,
        left: r.left,
        right: r.right,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      });
    };
    window.addEventListener("resize", onChange);
    window.addEventListener("scroll", onChange, true);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("resize", onChange);
      window.removeEventListener("scroll", onChange, true);
    };
  }, [selector]);

  if (!rect) return null;
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2 }}
      className="fixed pointer-events-none z-[60]"
      style={{
        top: rect.top - 6,
        left: rect.left - 6,
        width: rect.width + 12,
        height: rect.height + 12,
        borderRadius: 10,
        border: "2px solid var(--onboarding-primary)",
        boxShadow:
          "0 0 0 4px color-mix(in srgb, var(--onboarding-primary) 22%, transparent)",
      }}
    />
  );
}

/** Light-weight outline(s) on the anchored element(s). Renders one
 *  ring per selector in [anchor, ...extraAnchors]. No backdrop dim,
 *  no pulse — just 2px purple border + soft halo per ring. */
export function AnchorOutline() {
  const { progress, currentStep, isActive } = useOnboarding();
  // Respect ``noOutline`` — some steps just navigate to a page where
  // the focus is obvious (e.g. GitHub Monitoring, Standup Digest).
  if (
    !progress ||
    !isActive ||
    currentStep?.variant !== "spotlight" ||
    currentStep.noOutline
  ) {
    return null;
  }
  const selectors = [
    currentStep.anchor,
    ...(currentStep.extraAnchors ?? []),
  ].filter(Boolean) as string[];
  if (selectors.length === 0) return null;
  return (
    <>
      {selectors.map((sel) => (
        <SingleAnchorOutline key={sel} selector={sel} />
      ))}
    </>
  );
}

/** Inline banner — takes its own height in the layout so the
 *  dashboard shifts down under it instead of being overlapped. */
export function TourBanner() {
  const {
    progress,
    currentStep,
    currentStepIndex,
    allSteps,
    isActive,
    next,
    back,
    skipCurrent,
    skipTour,
  } = useOnboarding();

  // Render nothing when tour isn't active or the current step is a
  // welcome/completion modal — the banner is only for spotlight steps.
  if (!progress || !isActive || !currentStep) return null;
  if (currentStep.variant !== "spotlight") return null;

  const spotlightSteps = allSteps.filter((s) => s.variant === "spotlight");
  const totalSteps = spotlightSteps.length;
  const stepNumber =
    spotlightSteps.findIndex((s) => s.id === currentStep.id) + 1;

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={currentStep.id}
        initial={{ opacity: 0, y: -4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.2 }}
        className="relative border-b shrink-0"
        style={{
          background:
            "linear-gradient(90deg, color-mix(in srgb, var(--onboarding-primary) 12%, var(--bg-surface)) 0%, color-mix(in srgb, var(--onboarding-accent) 10%, var(--bg-surface)) 100%)",
          borderColor:
            "color-mix(in srgb, var(--onboarding-primary) 35%, transparent)",
        }}
        role="region"
        aria-label="Product tour"
      >
        <div className="mx-auto max-w-[1600px] px-4 sm:px-5 lg:px-6 py-2.5 flex items-center gap-3">
          {/* Icon */}
          <div
            className="hidden sm:flex h-8 w-8 items-center justify-center rounded-lg shrink-0"
            style={{ background: "var(--onboarding-gradient-soft)" }}
          >
            <Sparkles
              size={15}
              style={{ color: "var(--onboarding-primary)" }}
            />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5 flex-wrap">
              <span
                className="text-[10px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--onboarding-primary)" }}
              >
                Step {stepNumber} of {totalSteps}
              </span>
              <span
                className="text-sm font-semibold"
                style={{ color: "var(--text-primary)" }}
              >
                {currentStep.title}
              </span>
            </div>
            <p
              className="text-xs leading-snug line-clamp-2"
              style={{ color: "var(--text-secondary)" }}
            >
              {currentStep.body}
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => skipCurrent()}
              className="hidden md:inline-block text-xs font-medium px-2.5 py-1.5 rounded-md transition-colors"
              style={{ color: "var(--text-secondary)" }}
              title="Skip this step"
            >
              Skip
            </button>
            {currentStepIndex > 1 && (
              <button
                onClick={() => back()}
                className="text-xs font-medium px-3 py-1.5 rounded-md border transition-colors"
                style={{
                  borderColor: "var(--border-subtle)",
                  color: "var(--text-primary)",
                  background: "var(--bg-surface)",
                }}
              >
                Back
              </button>
            )}
            <button
              onClick={() => next()}
              className="text-xs font-semibold px-3.5 py-1.5 rounded-md flex items-center gap-1.5"
              style={{
                background: "var(--onboarding-gradient)",
                color: "white",
              }}
            >
              {stepNumber === totalSteps ? "Finish" : "Next"}
              <ArrowRight size={12} />
            </button>
            <button
              onClick={() => skipTour()}
              className="ml-1 p-1 rounded transition-colors"
              style={{ color: "var(--text-tertiary)" }}
              aria-label="Exit tour"
              title="Exit tour"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Slim progress bar at the bottom of the banner */}
        <div
          className="h-[2px]"
          style={{ background: "color-mix(in srgb, var(--onboarding-primary) 12%, transparent)" }}
        >
          <motion.div
            className="h-full"
            style={{ background: "var(--onboarding-gradient)" }}
            animate={{ width: `${(stepNumber / totalSteps) * 100}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

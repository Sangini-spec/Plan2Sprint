"use client";

/**
 * SpotlightCard — anchored tour card with dim backdrop + spotlight ring.
 *
 * Looks for the step's CSS anchor in the DOM, measures it, dims the rest
 * of the page, draws a glowing ring around the anchor, and positions the
 * card next to it (auto-flips based on viewport space).
 *
 * If the anchor isn't found (e.g. the user navigated away mid-step), the
 * card falls back to a centered modal so the user is never stranded.
 */

import { useEffect, useLayoutEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, X } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

const CARD_WIDTH = 340;
const CARD_GAP = 14; // gap between anchor and card
const VIEWPORT_PADDING = 16;

interface Rect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

/** Choose card position based on which side has the most space. */
function pickPosition(
  anchorRect: Rect,
  preferred: "top" | "bottom" | "left" | "right" | "auto" | undefined,
  cardHeight: number,
): { top: number; left: number; arrow: "top" | "bottom" | "left" | "right" } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  const spaceRight = vw - anchorRect.right;
  const spaceLeft = anchorRect.left;
  const spaceTop = anchorRect.top;
  const spaceBottom = vh - anchorRect.bottom;

  const fitsRight = spaceRight >= CARD_WIDTH + CARD_GAP + VIEWPORT_PADDING;
  const fitsLeft = spaceLeft >= CARD_WIDTH + CARD_GAP + VIEWPORT_PADDING;
  const fitsBottom = spaceBottom >= cardHeight + CARD_GAP + VIEWPORT_PADDING;
  const fitsTop = spaceTop >= cardHeight + CARD_GAP + VIEWPORT_PADDING;

  let placement: "top" | "bottom" | "left" | "right";

  if (preferred && preferred !== "auto") {
    const fits = {
      top: fitsTop,
      bottom: fitsBottom,
      left: fitsLeft,
      right: fitsRight,
    };
    placement = fits[preferred]
      ? preferred
      : (["bottom", "top", "right", "left"] as const).find((p) => fits[p]) ??
        "bottom";
  } else {
    placement =
      (["bottom", "right", "top", "left"] as const).find((p) =>
        p === "bottom"
          ? fitsBottom
          : p === "top"
          ? fitsTop
          : p === "right"
          ? fitsRight
          : fitsLeft,
      ) ?? "bottom";
  }

  let top: number;
  let left: number;

  switch (placement) {
    case "bottom":
      top = anchorRect.bottom + CARD_GAP;
      // Prefer aligning the card's centre with the anchor's centre,
      // but if that pushes the card past the viewport edge, snap to
      // the nearer side of the anchor instead. This stops cards
      // anchored to topbar items (right side) from being centred under
      // them and overflowing the viewport.
      {
        const centered = anchorRect.left + anchorRect.width / 2 - CARD_WIDTH / 2;
        const maxLeft = vw - CARD_WIDTH - VIEWPORT_PADDING;
        if (centered > maxLeft) {
          // Snap card's RIGHT edge to anchor's RIGHT edge.
          left = anchorRect.right - CARD_WIDTH;
        } else if (centered < VIEWPORT_PADDING) {
          // Snap card's LEFT edge to anchor's LEFT edge.
          left = anchorRect.left;
        } else {
          left = centered;
        }
      }
      break;
    case "top":
      top = anchorRect.top - cardHeight - CARD_GAP;
      {
        const centered = anchorRect.left + anchorRect.width / 2 - CARD_WIDTH / 2;
        const maxLeft = vw - CARD_WIDTH - VIEWPORT_PADDING;
        if (centered > maxLeft) {
          left = anchorRect.right - CARD_WIDTH;
        } else if (centered < VIEWPORT_PADDING) {
          left = anchorRect.left;
        } else {
          left = centered;
        }
      }
      break;
    case "right":
      top = anchorRect.top + anchorRect.height / 2 - cardHeight / 2;
      left = anchorRect.right + CARD_GAP;
      break;
    case "left":
      top = anchorRect.top + anchorRect.height / 2 - cardHeight / 2;
      left = anchorRect.left - CARD_WIDTH - CARD_GAP;
      break;
  }

  // Final clamp to viewport — never let a card end up off-screen.
  top = Math.max(VIEWPORT_PADDING, Math.min(vh - cardHeight - VIEWPORT_PADDING, top));
  left = Math.max(VIEWPORT_PADDING, Math.min(vw - CARD_WIDTH - VIEWPORT_PADDING, left));

  return {
    top,
    left,
    arrow:
      placement === "bottom"
        ? "top"
        : placement === "top"
        ? "bottom"
        : placement === "right"
        ? "left"
        : "right",
  };
}

export function SpotlightCard() {
  const {
    progress,
    currentStep,
    currentStepIndex,
    allSteps,
    next,
    back,
    skipCurrent,
    skipTour,
  } = useOnboarding();

  const [anchorRect, setAnchorRect] = useState<Rect | null>(null);
  const [cardHeight, setCardHeight] = useState(220);

  // Locate the anchor on every step change + on resize.
  useLayoutEffect(() => {
    if (!currentStep?.anchor) {
      setAnchorRect(null);
      return;
    }
    let raf: number | null = null;
    let retries = 0;
    const MAX_RETRIES = 30; // ~1s at 60fps — gives the route time to mount

    function measure() {
      const el = document.querySelector(currentStep!.anchor!) as HTMLElement | null;
      if (!el) {
        if (retries++ < MAX_RETRIES) {
          raf = requestAnimationFrame(measure);
        } else {
          setAnchorRect(null);
        }
        return;
      }
      const r = el.getBoundingClientRect();
      setAnchorRect({
        top: r.top,
        left: r.left,
        right: r.right,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      });
      // Bring the anchor into view if it's off-screen. Use ``start``
      // alignment (anchor lands near the top of the viewport) so the
      // card has the full lower half to occupy — ``center`` was
      // pushing the card below the anchor's centered position, often
      // off the bottom edge or into the checklist-widget area.
      // Instant scroll so the captured anchorRect immediately matches
      // the rendered position.
      if (r.top < 0 || r.bottom > window.innerHeight) {
        el.scrollIntoView({ block: "start", behavior: "auto" });
        // Re-measure after the scroll so the card positions against
        // the new viewport-relative rect.
        const r2 = el.getBoundingClientRect();
        setAnchorRect({
          top: r2.top,
          left: r2.left,
          right: r2.right,
          bottom: r2.bottom,
          width: r2.width,
          height: r2.height,
        });
      }
    }
    raf = requestAnimationFrame(measure);

    const onResize = () => measure();
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onResize, true);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onResize, true);
    };
  }, [currentStep?.id, currentStep?.anchor]);

  // Track card height for accurate positioning.
  const cardRef = (el: HTMLDivElement | null) => {
    if (el) setCardHeight(el.offsetHeight);
  };

  if (!progress || !currentStep) return null;
  if (currentStep.variant !== "spotlight") return null;

  // Count only spotlight steps for the user-facing "Step X of Y"
  // display. The welcome modal and completion modal are bookends —
  // showing them in the count would mean "Step 2 of 13" on the first
  // real step, which is confusing. With this filter, the first real
  // step becomes "Step 1 of 11".
  const spotlightSteps = allSteps.filter((s) => s.variant === "spotlight");
  const totalSteps = spotlightSteps.length;
  const stepNumber =
    spotlightSteps.findIndex((s) => s.id === currentStep.id) + 1;

  // Fallback to centered modal if anchor not found.
  const useFallback = !anchorRect;
  const position = useFallback
    ? null
    : pickPosition(anchorRect!, currentStep.anchorPosition, cardHeight);

  return (
    <>
      {/* Backdrop with a real cutout over the anchor.
          The trick: a transparent box at the anchor's position with a
          MASSIVE box-shadow (9999px spread) acts as both the dim
          backdrop AND the cutout — the shadow extends outward to
          cover the whole viewport, but the box itself stays clear so
          the anchored element shines through at its natural colour.
          A full-screen dim div with a "ring on top" can't do this —
          the underlying element is always dimmed by the backdrop. */}
      {anchorRect ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.25 }}
          className="fixed pointer-events-none z-[95]"
          style={{
            top: anchorRect.top - 8,
            left: anchorRect.left - 8,
            width: anchorRect.width + 16,
            height: anchorRect.height + 16,
            borderRadius: 12,
            boxShadow: "0 0 0 9999px var(--onboarding-backdrop)",
          }}
        />
      ) : (
        /* Fallback path — no anchor found, dim the whole viewport */
        <div className="fixed inset-0 z-[95] pointer-events-none onb-backdrop" />
      )}

      {/* Spotlight ring with pulse — pulls the eye to the anchor. */}
      {anchorRect && (
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{
            opacity: 1,
            scale: 1,
          }}
          transition={{ duration: 0.25 }}
          className="fixed onb-spotlight-ring onb-spotlight-pulse pointer-events-none z-[96]"
          style={{
            top: anchorRect.top - 8,
            left: anchorRect.left - 8,
            width: anchorRect.width + 16,
            height: anchorRect.height + 16,
          }}
        />
      )}

      {/* Tiny arrow pointing from the card to the anchor.
          Uses CSS borders to draw a true triangle (rotated rectangle
          looked like a fuzzy diamond). 7px sides for a subtle hint
          without dominating the card edge. */}
      {anchorRect && position && (() => {
        const SIZE = 7;
        const COLOR = "var(--onboarding-primary)";
        const baseStyle: React.CSSProperties = {
          position: "fixed",
          zIndex: 99,
          width: 0,
          height: 0,
          pointerEvents: "none",
        };
        const dir = position.arrow;
        if (dir === "top") {
          return (
            <div style={{
              ...baseStyle,
              top: position.top - SIZE,
              left: position.left + CARD_WIDTH / 2 - SIZE,
              borderLeft: `${SIZE}px solid transparent`,
              borderRight: `${SIZE}px solid transparent`,
              borderBottom: `${SIZE}px solid ${COLOR}`,
            }} />
          );
        }
        if (dir === "bottom") {
          return (
            <div style={{
              ...baseStyle,
              top: position.top + cardHeight,
              left: position.left + CARD_WIDTH / 2 - SIZE,
              borderLeft: `${SIZE}px solid transparent`,
              borderRight: `${SIZE}px solid transparent`,
              borderTop: `${SIZE}px solid ${COLOR}`,
            }} />
          );
        }
        if (dir === "left") {
          return (
            <div style={{
              ...baseStyle,
              top: position.top + cardHeight / 2 - SIZE,
              left: position.left - SIZE,
              borderTop: `${SIZE}px solid transparent`,
              borderBottom: `${SIZE}px solid transparent`,
              borderRight: `${SIZE}px solid ${COLOR}`,
            }} />
          );
        }
        // right
        return (
          <div style={{
            ...baseStyle,
            top: position.top + cardHeight / 2 - SIZE,
            left: position.left + CARD_WIDTH,
            borderTop: `${SIZE}px solid transparent`,
            borderBottom: `${SIZE}px solid transparent`,
            borderLeft: `${SIZE}px solid ${COLOR}`,
          }} />
        );
      })()}

      {/* Card */}
      <motion.div
        ref={cardRef}
        key={currentStep.id}
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.2 }}
        className="onb-card fixed z-[99]"
        style={{
          width: CARD_WIDTH,
          ...(useFallback
            ? {
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
              }
            : { top: position!.top, left: position!.left }),
        }}
        role="dialog"
        aria-modal="false"
        aria-labelledby={`onb-step-${currentStep.id}`}
      >
        <div className="onb-card-header-stripe" />
        <div className="p-5">
          {/* Header — step number + dots + skip */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2.5">
              <span
                className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--onboarding-primary)" }}
              >
                Step {stepNumber} of {totalSteps}
              </span>
            </div>
            <button
              onClick={() => skipTour()}
              className="text-[var(--onboarding-card-text-muted)] hover:text-[var(--onboarding-card-text)] transition-colors"
              aria-label="Skip tour"
            >
              <X size={16} />
            </button>
          </div>

          {/* Progress dots — one per spotlight step. Skip the welcome
              and completion bookends so the dot count matches the
              "Step X of Y" header. */}
          <div className="flex items-center gap-1.5 mb-4 flex-wrap">
            {spotlightSteps.map((s, i) => (
              <span
                key={s.id}
                className="onb-progress-dot"
                data-state={
                  i < stepNumber - 1
                    ? "completed"
                    : i === stepNumber - 1
                    ? "current"
                    : "pending"
                }
              />
            ))}
          </div>

          {/* Title + body */}
          <h3
            id={`onb-step-${currentStep.id}`}
            className="text-base font-semibold mb-2"
            style={{ color: "var(--onboarding-card-text)" }}
          >
            {currentStep.title}
          </h3>
          <p
            className="text-sm leading-relaxed mb-5"
            style={{ color: "var(--onboarding-card-text-muted)" }}
          >
            {currentStep.body}
          </p>

          {/* Footer */}
          <div className="flex items-center justify-between gap-2">
            <button
              onClick={() => skipCurrent()}
              className="text-xs font-medium transition-colors"
              style={{ color: "var(--onboarding-card-text-muted)" }}
            >
              Skip this step
            </button>
            <div className="flex items-center gap-2">
              {currentStepIndex > 1 && (
                <button
                  onClick={() => back()}
                  className="onb-cta-secondary text-sm"
                  style={{ padding: "8px 14px" }}
                >
                  Back
                </button>
              )}
              <button
                onClick={() => next()}
                className="onb-cta text-sm flex items-center gap-1.5"
                style={{ padding: "8px 14px" }}
              >
                {stepNumber === totalSteps - 1 ? "Finish" : "Next"}
                <ArrowRight size={14} />
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </>
  );
}

"use client";

/**
 * InlineTooltip — small contextual popover that appears next to a
 * specific UI element during a tour step.
 *
 * Different from the main banner: it points at one control, has its
 * own dismissible "OK" button, and only renders while the active
 * step has it in ``step.tooltips``. Used to highlight secondary
 * controls that don't deserve a whole tour step (e.g. the Regenerate
 * button on the sprint-planning step).
 *
 * Once dismissed, the tooltip remembers its dismissal in
 * sessionStorage (per step+selector key) so it doesn't keep popping
 * if the user navigates back to the step.
 */

import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Lightbulb, X } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

interface Rect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

const TOOLTIP_WIDTH = 260;
const TOOLTIP_GAP = 10;

function useAnchorRect(selector: string | null): Rect | null {
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
      const el = document.querySelector(selector!) as HTMLElement | null;
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
    }
    raf = requestAnimationFrame(measure);
    const onChange = () => {
      const el = document.querySelector(selector!) as HTMLElement | null;
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
  return rect;
}

function position(
  anchor: Rect,
  preferred: "top" | "bottom" | "left" | "right",
  cardHeight: number,
): { top: number; left: number } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let top: number;
  let left: number;
  switch (preferred) {
    case "bottom":
      top = anchor.bottom + TOOLTIP_GAP;
      left = anchor.left + anchor.width / 2 - TOOLTIP_WIDTH / 2;
      break;
    case "top":
      top = anchor.top - cardHeight - TOOLTIP_GAP;
      left = anchor.left + anchor.width / 2 - TOOLTIP_WIDTH / 2;
      break;
    case "right":
      top = anchor.top + anchor.height / 2 - cardHeight / 2;
      left = anchor.right + TOOLTIP_GAP;
      break;
    case "left":
      top = anchor.top + anchor.height / 2 - cardHeight / 2;
      left = anchor.left - TOOLTIP_WIDTH - TOOLTIP_GAP;
      break;
  }
  // Clamp to viewport
  top = Math.max(8, Math.min(vh - cardHeight - 8, top));
  left = Math.max(8, Math.min(vw - TOOLTIP_WIDTH - 8, left));
  return { top, left };
}

interface SingleTooltipProps {
  selector: string;
  body: string;
  preferred: "top" | "bottom" | "left" | "right";
  onDismiss: () => void;
}

function SingleTooltip({ selector, body, preferred, onDismiss }: SingleTooltipProps) {
  const rect = useAnchorRect(selector);
  const [cardHeight, setCardHeight] = useState(100);
  if (!rect) return null;
  const pos = position(rect, preferred, cardHeight);
  return (
    <motion.div
      ref={(el) => {
        if (el) setCardHeight(el.offsetHeight);
      }}
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.15 }}
      className="fixed z-[97] onb-card"
      style={{
        top: pos.top,
        left: pos.left,
        width: TOOLTIP_WIDTH,
      }}
    >
      <div className="onb-card-header-stripe" />
      <div className="p-3.5">
        <div className="flex items-start gap-2 mb-2">
          <Lightbulb
            size={14}
            style={{ color: "var(--onboarding-primary)" }}
            className="shrink-0 mt-0.5"
          />
          <p
            className="text-xs leading-relaxed flex-1"
            style={{ color: "var(--onboarding-card-text)" }}
          >
            {body}
          </p>
          <button
            onClick={onDismiss}
            className="shrink-0"
            style={{ color: "var(--onboarding-card-text-muted)" }}
            aria-label="Dismiss tooltip"
          >
            <X size={12} />
          </button>
        </div>
        <div className="flex justify-end">
          <button
            onClick={onDismiss}
            className="text-[11px] font-semibold px-3 py-1 rounded"
            style={{
              background: "var(--onboarding-gradient)",
              color: "white",
            }}
          >
            OK
          </button>
        </div>
      </div>
    </motion.div>
  );
}

export function InlineTooltips() {
  const { currentStep, isActive } = useOnboarding();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const tooltips = useMemo(() => {
    if (!isActive || currentStep?.variant !== "spotlight") return [];
    return currentStep.tooltips ?? [];
  }, [currentStep, isActive]);

  // Reset dismissed list when the step changes — each step's tooltips
  // are independent.
  useEffect(() => {
    setDismissed(new Set());
  }, [currentStep?.id]);

  if (tooltips.length === 0) return null;

  return (
    <AnimatePresence>
      {tooltips.map((t) => {
        const key = `${currentStep?.id}::${t.selector}`;
        if (dismissed.has(key)) return null;
        return (
          <SingleTooltip
            key={key}
            selector={t.selector}
            body={t.body}
            preferred={t.position ?? "bottom"}
            onDismiss={() =>
              setDismissed((d) => {
                const next = new Set(d);
                next.add(key);
                return next;
              })
            }
          />
        );
      })}
    </AnimatePresence>
  );
}

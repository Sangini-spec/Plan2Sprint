"use client";

/* -------------------------------------------------------------------------- */
/*  NOTES BUTTON — top bar trigger                                             */
/*                                                                             */
/*  Gradient-animated pill next to Connect Tools. Opens the Notes drawer.     */
/*  Available to every role (PO, dev, stakeholder, admin).                    */
/* -------------------------------------------------------------------------- */

import { useState, useEffect } from "react";
import { StickyNote } from "lucide-react";
import { cn } from "@/lib/utils";
import { NotesDrawer } from "./notes-drawer";

export function NotesButton() {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState<number | null>(null);

  // Lightweight count fetch — just for the badge
  useEffect(() => {
    let cancelled = false;
    const fetchCount = async () => {
      try {
        const res = await fetch("/api/notes?limit=200");
        if (!cancelled && res.ok) {
          const data = await res.json();
          setCount((data.notes || []).length);
        }
      } catch { /* ignore */ }
    };
    fetchCount();
    return () => { cancelled = true; };
  }, [open]);  // refetch when drawer closes so the badge is fresh

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={cn(
          "relative inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5",
          "text-[13px] font-medium cursor-pointer transition-all duration-200",
          "text-[var(--text-primary)]",
          "hover:shadow-md",
          // Gradient animated border via a ::before layer using padding-box trick
          "notes-btn",
        )}
      >
        <StickyNote size={14} />
        <span className="hidden sm:inline">Notes</span>
        {count !== null && count > 0 && (
          <span className="ml-0.5 inline-flex items-center justify-center rounded-full bg-gradient-to-r from-[#3b82f6] to-[#10b981] px-1.5 py-0.5 text-[10px] font-bold text-white min-w-[18px]">
            {count}
          </span>
        )}
        <style jsx>{`
          .notes-btn {
            background-image:
              linear-gradient(var(--bg-surface), var(--bg-surface)),
              linear-gradient(90deg, #3b82f6, #06b6d4, #10b981, #3b82f6);
            background-origin: border-box;
            background-clip: padding-box, border-box;
            background-size: 200% 200%;
            border: 1.5px solid transparent;
            animation: notesBtnShift 6s linear infinite;
          }
          .notes-btn:hover {
            animation-duration: 2.5s;
          }
          @keyframes notesBtnShift {
            0%   { background-position: 0% 50%, 0% 50%; }
            50%  { background-position: 0% 50%, 100% 50%; }
            100% { background-position: 0% 50%, 0% 50%; }
          }
        `}</style>
      </button>
      <NotesDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}

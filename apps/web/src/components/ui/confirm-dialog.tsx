"use client";

import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "default";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={onCancel}
          />

          {/* Dialog */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.15 }}
            className="relative w-full max-w-sm mx-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] shadow-xl p-6"
          >
            <div className="flex items-start gap-3">
              {variant === "danger" && (
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-rag-red)]/10">
                  <AlertTriangle className="h-4.5 w-4.5 text-[var(--color-rag-red)]" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {title}
                </h3>
                <p className="mt-1.5 text-xs text-[var(--text-secondary)] leading-relaxed">
                  {description}
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-5">
              <Button variant="ghost" size="sm" onClick={onCancel}>
                {cancelLabel}
              </Button>
              <Button
                variant={variant === "danger" ? "primary" : "primary"}
                size="sm"
                onClick={onConfirm}
                className={
                  variant === "danger"
                    ? "!bg-[var(--color-rag-red)] hover:!bg-[var(--color-rag-red)]/90 !shadow-none !bg-none"
                    : ""
                }
              >
                {confirmLabel}
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

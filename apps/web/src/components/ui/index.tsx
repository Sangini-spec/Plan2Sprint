"use client";

import React, { forwardRef, useEffect, useRef, useState } from "react";
import {
  motion,
  useInView,
  useMotionValue,
  useSpring,
  AnimatePresence,
  type HTMLMotionProps,
} from "framer-motion";
import { ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/utils";

/* ==========================================================================
   1. BUTTON
   ========================================================================== */

type ButtonVariant = "primary" | "secondary" | "ghost";
type ButtonSize = "sm" | "md" | "lg";

type ButtonBaseProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: React.ReactNode;
  className?: string;
};

type ButtonAsButton = ButtonBaseProps &
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, keyof ButtonBaseProps> & {
    href?: undefined;
  };

type ButtonAsAnchor = ButtonBaseProps &
  Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, keyof ButtonBaseProps> & {
    href: string;
  };

export type ButtonProps = ButtonAsButton | ButtonAsAnchor;

const sizeClasses: Record<ButtonSize, string> = {
  sm: "px-4 py-2 text-sm rounded-lg gap-1.5",
  md: "px-6 py-2.5 text-sm rounded-xl gap-2",
  lg: "px-8 py-3.5 text-base rounded-xl gap-2.5",
};

const variantClasses: Record<ButtonVariant, string> = {
  primary: [
    "text-white font-semibold",
    "bg-[image:var(--gradient-cta)]",
    "shadow-lg shadow-[var(--color-brand-secondary)]/20",
    "hover:shadow-xl hover:shadow-[var(--color-brand-secondary)]/30",
    "hover:bg-[image:var(--gradient-cta-hover)]",
    "active:scale-[0.98]",
  ].join(" "),
  secondary: [
    "bg-transparent font-medium",
    "border border-[var(--border-subtle)]",
    "text-[var(--text-primary)]",
    "hover:bg-[var(--bg-surface-raised)]",
    "hover:border-[var(--color-brand-secondary)]/40",
  ].join(" "),
  ghost: [
    "bg-transparent font-medium",
    "text-[var(--text-secondary)]",
    "hover:text-[var(--text-primary)]",
    "hover:bg-[var(--bg-surface-raised)]",
  ].join(" "),
};

export const Button = forwardRef<
  HTMLButtonElement | HTMLAnchorElement,
  ButtonProps
>(({ variant = "primary", size = "md", className, children, ...props }, ref) => {
  const classes = cn(
    "inline-flex items-center justify-center whitespace-nowrap transition-all duration-200 ease-out",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-secondary)] focus-visible:ring-offset-2",
    "disabled:pointer-events-none disabled:opacity-50",
    "hover:scale-[1.02] active:scale-[0.98]",
    "cursor-pointer select-none",
    sizeClasses[size],
    variantClasses[variant],
    className
  );

  if ("href" in props && props.href !== undefined) {
    const { href, ...anchorProps } = props as ButtonAsAnchor;
    return (
      <a
        ref={ref as React.Ref<HTMLAnchorElement>}
        href={href}
        className={classes}
        {...anchorProps}
      >
        {children}
      </a>
    );
  }

  const buttonProps = props as ButtonAsButton;
  return (
    <button
      ref={ref as React.Ref<HTMLButtonElement>}
      className={classes}
      {...buttonProps}
    >
      {children}
    </button>
  );
});

Button.displayName = "Button";

/* ==========================================================================
   2. GLASS CARD
   ========================================================================== */

export interface GlassCardProps extends HTMLMotionProps<"div"> {
  children: React.ReactNode;
  className?: string;
  gradient?: boolean;
}

export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  ({ children, className, gradient = false, ...props }, ref) => {
    return (
      <motion.div
        ref={ref}
        whileHover={{ y: -8, transition: { duration: 0.3, ease: "easeOut" } }}
        className={cn(
          "relative rounded-2xl p-px overflow-hidden",
          gradient
            ? "bg-[image:var(--gradient-card-border)]"
            : "bg-[var(--border-subtle)]",
          className
        )}
        {...props}
      >
        {/* Inner card */}
        <div
          className={cn(
            "relative h-full w-full rounded-[15px]",
            "bg-[var(--bg-surface)]/80 backdrop-blur-xl",
            "p-6",
            "shadow-lg shadow-black/5 dark:shadow-black/20",
            "hover:shadow-xl hover:shadow-black/10 dark:hover:shadow-black/30",
            "transition-shadow duration-300"
          )}
        >
          {children}
        </div>
      </motion.div>
    );
  }
);

GlassCard.displayName = "GlassCard";

/* ==========================================================================
   3. BADGE
   ========================================================================== */

type BadgeVariant = "brand" | "rag-green" | "rag-amber" | "rag-red";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

const badgeVariantClasses: Record<BadgeVariant, string> = {
  brand: [
    "border border-[var(--color-brand-secondary)]/30",
    "text-[var(--color-brand-secondary)]",
    "bg-[var(--color-brand-secondary)]/10",
  ].join(" "),
  "rag-green": [
    "border border-[var(--color-rag-green)]/30",
    "text-[var(--color-rag-green)]",
    "bg-[var(--color-rag-green)]/10",
  ].join(" "),
  "rag-amber": [
    "border border-[var(--color-rag-amber)]/30",
    "text-[var(--color-rag-amber)]",
    "bg-[var(--color-rag-amber)]/10",
  ].join(" "),
  "rag-red": [
    "border border-[var(--color-rag-red)]/30",
    "text-[var(--color-rag-red)]",
    "bg-[var(--color-rag-red)]/10",
  ].join(" "),
};

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ variant = "brand", className, children, ...props }, ref) => {
    return (
      <span
        ref={ref}
        className={cn(
          "inline-flex items-center rounded-full px-3 py-1",
          "text-xs font-semibold leading-none",
          "transition-colors duration-200",
          badgeVariantClasses[variant],
          className
        )}
        {...props}
      >
        {children}
      </span>
    );
  }
);

Badge.displayName = "Badge";

/* ==========================================================================
   4. SECTION LABEL
   ========================================================================== */

export interface SectionLabelProps
  extends React.HTMLAttributes<HTMLParagraphElement> {
  children: React.ReactNode;
  className?: string;
}

export const SectionLabel = forwardRef<HTMLParagraphElement, SectionLabelProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <p
        ref={ref}
        className={cn(
          "text-xs font-bold uppercase tracking-[0.2em]",
          "text-[var(--color-brand-secondary)]",
          "mb-4",
          className
        )}
        {...props}
      >
        {children}
      </p>
    );
  }
);

SectionLabel.displayName = "SectionLabel";

/* ==========================================================================
   5. SECTION HEADING
   ========================================================================== */

export interface SectionHeadingProps
  extends React.HTMLAttributes<HTMLHeadingElement> {
  children: React.ReactNode;
  gradient?: boolean;
  className?: string;
  as?: "h1" | "h2" | "h3";
}

export const SectionHeading = forwardRef<
  HTMLHeadingElement,
  SectionHeadingProps
>(({ gradient = false, className, children, as: Tag = "h2", ...props }, ref) => {
  return (
    <Tag
      ref={ref}
      className={cn(
        "text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl",
        "leading-[1.1]",
        gradient && "gradient-text",
        !gradient && "text-[var(--text-primary)]",
        className
      )}
      {...props}
    >
      {children}
    </Tag>
  );
});

SectionHeading.displayName = "SectionHeading";

/* ==========================================================================
   6. ANIMATED COUNTER
   ========================================================================== */

export interface AnimatedCounterProps {
  /** The target number to count up to */
  target: number;
  /** Duration of the counting animation in seconds */
  duration?: number;
  /** Optional prefix (e.g., "$", "#") */
  prefix?: string;
  /** Optional suffix (e.g., "%", "+", "k") */
  suffix?: string;
  /** Number of decimal places */
  decimals?: number;
  /** Additional class names */
  className?: string;
}

export function AnimatedCounter({
  target,
  duration = 2,
  prefix = "",
  suffix = "",
  decimals = 0,
  className,
}: AnimatedCounterProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-100px" });
  const motionValue = useMotionValue(0);
  const springValue = useSpring(motionValue, {
    duration: duration * 1000,
    bounce: 0,
  });

  useEffect(() => {
    if (isInView) {
      motionValue.set(target);
    }
  }, [isInView, motionValue, target]);

  useEffect(() => {
    const unsubscribe = springValue.on("change", (latest) => {
      if (ref.current) {
        const formatted =
          decimals > 0
            ? latest.toFixed(decimals)
            : Math.round(latest).toLocaleString();
        ref.current.textContent = `${prefix}${formatted}${suffix}`;
      }
    });

    return unsubscribe;
  }, [springValue, prefix, suffix, decimals]);

  return (
    <span
      ref={ref}
      className={cn(
        "tabular-nums font-bold text-[var(--text-primary)]",
        className
      )}
    >
      {prefix}0{suffix}
    </span>
  );
}

/* ==========================================================================
   7. INPUT
   ========================================================================== */

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          "flex h-10 w-full rounded-xl border px-3 py-2 text-sm",
          "bg-[var(--bg-surface-raised)] border-[var(--border-subtle)]",
          "text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50",
          "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent",
          "transition-all duration-200",
          "disabled:cursor-not-allowed disabled:opacity-50",
          error && "border-[var(--color-rag-red)] focus:ring-[var(--color-rag-red)]",
          className
        )}
        {...props}
      />
    );
  }
);

Input.displayName = "Input";

/* ==========================================================================
   8. TEXTAREA
   ========================================================================== */

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={cn(
          "flex min-h-[80px] w-full rounded-xl border px-3 py-2 text-sm",
          "bg-[var(--bg-surface-raised)] border-[var(--border-subtle)]",
          "text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50",
          "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent",
          "transition-all duration-200 resize-none",
          "disabled:cursor-not-allowed disabled:opacity-50",
          error && "border-[var(--color-rag-red)] focus:ring-[var(--color-rag-red)]",
          className
        )}
        {...props}
      />
    );
  }
);

Textarea.displayName = "Textarea";

/* ==========================================================================
   9. SELECT
   ========================================================================== */

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  error?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, error, children, ...props }, ref) => {
    return (
      <div className="relative">
        <select
          ref={ref}
          className={cn(
            "flex h-10 w-full appearance-none rounded-xl border px-3 py-2 pr-8 text-sm",
            "bg-[var(--bg-surface-raised)] border-[var(--border-subtle)]",
            "text-[var(--text-primary)]",
            "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent",
            "transition-all duration-200",
            "disabled:cursor-not-allowed disabled:opacity-50",
            error && "border-[var(--color-rag-red)] focus:ring-[var(--color-rag-red)]",
            className
          )}
          {...props}
        >
          {children}
        </select>
        <ChevronDown
          size={14}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] pointer-events-none"
        />
      </div>
    );
  }
);

Select.displayName = "Select";

/* ==========================================================================
   10. FORM FIELD
   ========================================================================== */

export interface FormFieldProps {
  label: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}

export function FormField({
  label,
  error,
  required,
  children,
  className,
}: FormFieldProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label className="text-sm font-medium text-[var(--text-primary)]">
        {label}
        {required && <span className="text-[var(--color-rag-red)] ml-0.5">*</span>}
      </label>
      {children}
      {error && (
        <p className="text-xs text-[var(--color-rag-red)]">{error}</p>
      )}
    </div>
  );
}

/* ==========================================================================
   11. AVATAR
   ========================================================================== */

export interface AvatarProps {
  src?: string;
  alt?: string;
  fallback: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const avatarSizes = {
  sm: "h-6 w-6 text-xs",
  md: "h-8 w-8 text-sm",
  lg: "h-10 w-10 text-base",
};

export function Avatar({ src, alt, fallback, size = "md", className }: AvatarProps) {
  const [imgError, setImgError] = useState(false);

  if (src && !imgError) {
    return (
      <img
        src={src}
        alt={alt ?? fallback}
        onError={() => setImgError(true)}
        className={cn(
          "rounded-full object-cover shrink-0",
          avatarSizes[size],
          className
        )}
      />
    );
  }

  return (
    <div
      className={cn(
        "flex items-center justify-center rounded-full shrink-0",
        "bg-[var(--color-brand-secondary)]/20 text-[var(--color-brand-secondary)] font-semibold",
        avatarSizes[size],
        className
      )}
      title={alt ?? fallback}
    >
      {fallback.charAt(0).toUpperCase()}
    </div>
  );
}

/* ==========================================================================
   12. TOOLTIP
   ========================================================================== */

export interface TooltipProps {
  content: string;
  children: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
}

export function Tooltip({ content, children, side = "top", className }: TooltipProps) {
  const [show, setShow] = useState(false);

  const positionClasses = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  };

  return (
    <div
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      <AnimatePresence>
        {show && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.1 }}
            className={cn(
              "absolute z-50 px-2.5 py-1.5 text-xs font-medium whitespace-nowrap",
              "rounded-lg bg-[var(--text-primary)] text-[var(--bg-base)]",
              "shadow-lg pointer-events-none",
              positionClasses[side]
            )}
          >
            {content}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ==========================================================================
   13. PROGRESS BAR
   ========================================================================== */

export interface ProgressProps {
  value: number; // 0-100
  max?: number;
  severity?: "GREEN" | "AMBER" | "RED";
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
  className?: string;
}

const progressSizes = {
  sm: "h-1.5",
  md: "h-2.5",
  lg: "h-4",
};

const progressColors = {
  GREEN: "bg-[var(--color-rag-green)]",
  AMBER: "bg-[var(--color-rag-amber)]",
  RED: "bg-[var(--color-rag-red)]",
};

export function Progress({
  value,
  max = 100,
  severity,
  size = "md",
  showLabel = false,
  className,
}: ProgressProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const barColor = severity
    ? progressColors[severity]
    : "bg-[var(--color-brand-secondary)]";

  return (
    <div className={cn("w-full", className)}>
      <div
        className={cn(
          "w-full rounded-full bg-[var(--bg-surface-raised)] overflow-hidden",
          progressSizes[size]
        )}
      >
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className={cn("h-full rounded-full", barColor)}
        />
      </div>
      {showLabel && (
        <span className="text-xs font-medium text-[var(--text-secondary)] mt-1">
          {Math.round(pct)}%
        </span>
      )}
    </div>
  );
}

/* ==========================================================================
   14. TABS
   ========================================================================== */

export interface TabItem {
  id: string;
  label: string;
}

export interface TabsProps {
  items: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ items, activeId, onChange, className }: TabsProps) {
  return (
    <div
      className={cn(
        "flex gap-1 rounded-xl bg-[var(--bg-surface-raised)] p-1",
        className
      )}
    >
      {items.map((item) => (
        <button
          key={item.id}
          onClick={() => onChange(item.id)}
          className={cn(
            "relative flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200 cursor-pointer",
            activeId === item.id
              ? "text-[var(--text-primary)]"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          )}
        >
          {activeId === item.id && (
            <motion.div
              layoutId="tab-active"
              className="absolute inset-0 rounded-lg bg-[var(--bg-surface)] shadow-sm"
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
            />
          )}
          <span className="relative z-10">{item.label}</span>
        </button>
      ))}
    </div>
  );
}

/* ==========================================================================
   15. SHEET (SLIDE-OVER DRAWER)
   ========================================================================== */

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  side?: "left" | "right";
  className?: string;
}

export function Sheet({
  open,
  onClose,
  title,
  children,
  side = "right",
  className,
}: SheetProps) {
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />
          <motion.div
            initial={{ x: side === "right" ? "100%" : "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: side === "right" ? "100%" : "-100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className={cn(
              "fixed inset-y-0 z-50 w-full max-w-md",
              side === "right" ? "right-0" : "left-0",
              "bg-[var(--bg-surface)] border-l border-[var(--border-subtle)]",
              "flex flex-col shadow-2xl",
              className
            )}
          >
            {title && (
              <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
                <h3 className="text-lg font-semibold text-[var(--text-primary)]">
                  {title}
                </h3>
                <button
                  onClick={onClose}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
                >
                  <X size={18} />
                </button>
              </div>
            )}
            <div className="flex-1 overflow-y-auto">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ==========================================================================
   16. DROPDOWN MENU
   ========================================================================== */

export interface DropdownMenuItem {
  label: string;
  icon?: React.ReactNode;
  onClick: () => void;
  variant?: "default" | "danger";
  disabled?: boolean;
}

export interface DropdownMenuProps {
  trigger: React.ReactNode;
  items: DropdownMenuItem[];
  align?: "left" | "right";
  className?: string;
}

export function DropdownMenu({
  trigger,
  items,
  align = "right",
  className,
}: DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={menuRef} className={cn("relative inline-flex", className)}>
      <div onClick={() => setOpen(!open)}>{trigger}</div>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className={cn(
              "absolute top-full mt-2 min-w-[180px] z-50",
              "rounded-xl border border-[var(--border-subtle)]",
              "bg-[var(--bg-surface)]/95 backdrop-blur-xl shadow-xl",
              "py-1",
              align === "right" ? "right-0" : "left-0"
            )}
          >
            {items.map((item, i) => (
              <button
                key={i}
                onClick={() => {
                  if (!item.disabled) {
                    item.onClick();
                    setOpen(false);
                  }
                }}
                disabled={item.disabled}
                className={cn(
                  "flex w-full items-center gap-2.5 px-4 py-2.5 text-sm transition-colors cursor-pointer",
                  item.disabled && "opacity-50 cursor-not-allowed",
                  item.variant === "danger"
                    ? "text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/5"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]"
                )}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

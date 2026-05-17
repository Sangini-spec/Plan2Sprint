"use client";

import React, { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTheme } from "next-themes";
import { Sun, Moon, Menu, X, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";
import { Logo } from "@/components/ui/logo";

/* -------------------------------------------------------------------------- */
/*  TYPES                                                                      */
/* -------------------------------------------------------------------------- */

interface NavLink {
  label: string;
  href: string;
}

/* -------------------------------------------------------------------------- */
/*  DATA                                                                       */
/* -------------------------------------------------------------------------- */

const NAV_LINKS: NavLink[] = [
  { label: "Features", href: "#features" },
  { label: "Solutions", href: "#solutions" },
  { label: "Pricing", href: "#pricing" },
  { label: "About", href: "#about" },
  { label: "Contact Us", href: "#contact" },
];

/* -------------------------------------------------------------------------- */
/*  SUB-COMPONENTS                                                             */
/* -------------------------------------------------------------------------- */

/** Animated underline link for the desktop nav */
function NavItem({ label, href }: NavLink) {
  return (
    <a
      href={href}
      className="group relative py-2 text-sm font-medium text-[var(--text-secondary)] transition-colors duration-200 hover:text-[var(--text-primary)]"
    >
      {label}
      {/* Underline that scales from center on hover */}
      <span
        className={cn(
          "absolute inset-x-0 -bottom-0.5 h-0.5 rounded-full",
          "bg-[var(--color-brand-secondary)]",
          "origin-center scale-x-0 transition-transform duration-300 ease-out",
          "group-hover:scale-x-100"
        )}
      />
    </a>
  );
}

/** Theme toggle button with smooth icon swap */
function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const toggle = useCallback(() => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark");
  }, [resolvedTheme, setTheme]);

  // Avoid hydration mismatch by rendering placeholder until mounted
  if (!mounted) {
    return (
      <button
        className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--text-secondary)]"
        aria-label="Toggle theme"
      >
        <span className="h-[18px] w-[18px]" />
      </button>
    );
  }

  const isDark = resolvedTheme === "dark";

  return (
    <button
      onClick={toggle}
      className={cn(
        "flex h-9 w-9 items-center justify-center rounded-lg",
        "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
        "hover:bg-[var(--bg-surface-raised)]",
        "transition-colors duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-secondary)]"
      )}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={isDark ? "moon" : "sun"}
          initial={{ y: -8, opacity: 0, rotate: -30 }}
          animate={{ y: 0, opacity: 1, rotate: 0 }}
          exit={{ y: 8, opacity: 0, rotate: 30 }}
          transition={{ duration: 0.2 }}
          className="flex items-center justify-center"
        >
          {isDark ? <Moon size={18} /> : <Sun size={18} />}
        </motion.span>
      </AnimatePresence>
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*  MOBILE DRAWER                                                              */
/* -------------------------------------------------------------------------- */

interface MobileDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

function MobileDrawer({ isOpen, onClose }: MobileDrawerProps) {
  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Drawer panel */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className={cn(
              "fixed inset-y-0 right-0 z-50 w-full max-w-sm",
              "bg-[var(--bg-surface)] border-l border-[var(--border-subtle)]",
              "flex flex-col"
            )}
          >
            {/* Drawer header */}
            <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-6 py-4">
              <Logo size="md" />
              <button
                onClick={onClose}
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-lg",
                  "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                  "hover:bg-[var(--bg-surface-raised)]",
                  "transition-colors duration-200"
                )}
                aria-label="Close menu"
              >
                <X size={20} />
              </button>
            </div>

            {/* Drawer links */}
            <nav className="flex-1 overflow-y-auto px-6 py-6">
              <ul className="space-y-1">
                {NAV_LINKS.map((link, i) => (
                  <motion.li
                    key={link.href}
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.05 * i, duration: 0.3 }}
                  >
                    <a
                      href={link.href}
                      onClick={onClose}
                      className={cn(
                        "flex items-center rounded-xl px-4 py-3 text-base font-medium",
                        "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                        "hover:bg-[var(--bg-surface-raised)]",
                        "transition-colors duration-200"
                      )}
                    >
                      {link.label}
                    </a>
                  </motion.li>
                ))}
              </ul>
            </nav>

            {/* Drawer footer */}
            <div className="border-t border-[var(--border-subtle)] px-6 py-6 space-y-3">
              <Button
                variant="secondary"
                size="lg"
                href="/login"
                onClick={onClose}
                className="w-full justify-center"
              >
                Log In
              </Button>
              <Button
                variant="primary"
                size="lg"
                href="/signup"
                onClick={onClose}
                className="w-full justify-center"
              >
                Get Started Free
                <ArrowRight size={16} />
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* -------------------------------------------------------------------------- */
/*  NAVBAR (MAIN EXPORT)                                                       */
/* -------------------------------------------------------------------------- */

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };

    // Set initial state
    handleScroll();

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <>
      <header
        className={cn(
          "fixed top-0 left-0 right-0 z-50 overflow-hidden",
          "transition-all duration-300 ease-out",
          "backdrop-blur-xl",
          scrolled
            ? [
                "bg-[var(--bg-surface)]/80",
                "border-b border-[var(--border-subtle)]",
                "shadow-sm shadow-black/5 dark:shadow-black/20",
              ]
            : "bg-[var(--bg-base)] border-b border-transparent"
        )}
      >
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          {/* ---- Left: Logo ---- */}
          <a href="/" className="flex shrink-0 items-center -my-1">
            <Logo size="lg" />
          </a>

          {/* ---- Center: Desktop Nav Links ---- */}
          <nav className="hidden items-center gap-8 lg:flex">
            {NAV_LINKS.map((link) => (
              <NavItem key={link.href} {...link} />
            ))}
          </nav>

          {/* ---- Right: Actions ---- */}
          <div className="flex items-center gap-2">
            {/* Theme toggle - always visible */}
            <ThemeToggle />

            {/* Desktop-only buttons */}
            <div className="hidden items-center gap-2 lg:flex">
              <Button variant="ghost" size="sm" href="/login">
                Log In
              </Button>
              <Button variant="primary" size="sm" href="/signup">
                Get Started Free
                <ArrowRight size={14} />
              </Button>
            </div>

            {/* Mobile hamburger */}
            <button
              onClick={() => setMobileOpen(true)}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-lg lg:hidden",
                "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                "hover:bg-[var(--bg-surface-raised)]",
                "transition-colors duration-200"
              )}
              aria-label="Open navigation menu"
            >
              <Menu size={20} />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile drawer */}
      <MobileDrawer
        isOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
      />
    </>
  );
}

export default Navbar;

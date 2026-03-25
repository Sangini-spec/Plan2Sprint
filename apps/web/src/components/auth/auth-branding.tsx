"use client";

import { motion } from "framer-motion";
import { AuroraBackground } from "@/components/ui/aurora-background";
import { Logo } from "@/components/ui/logo";

export function AuthBranding() {
  return (
    <div className="hidden lg:flex lg:w-1/2 overflow-hidden">
      <AuroraBackground>
        <motion.div
          initial={{ opacity: 0.0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{
            delay: 0.2,
            duration: 0.8,
            ease: "easeInOut",
          }}
          className="relative flex flex-col items-center justify-center px-12"
        >
          <div className="mb-2">
            <Logo size="lg" />
          </div>

          <p className="text-slate-900 dark:text-white/90 font-semibold text-center text-lg tracking-wide mb-3">
            The Brain of your Agile Stack
          </p>

          <p className="text-slate-600 dark:text-neutral-300 text-center text-sm max-w-xs leading-relaxed">
            AI-powered sprint planning for engineering teams. Ship faster, meet smarter.
          </p>

          <div className="mt-8 flex flex-wrap justify-center gap-2.5">
            {["AI Sprint Plans", "Async Standups", "Team Health", "Smart Insights"].map((f) => (
              <span
                key={f}
                className="rounded-full bg-slate-900/10 dark:bg-white/10 backdrop-blur-sm border border-slate-900/20 dark:border-white/20 px-4 py-1.5 text-sm text-slate-800 dark:text-white/90 font-medium"
              >
                {f}
              </span>
            ))}
          </div>
        </motion.div>
      </AuroraBackground>
    </div>
  );
}

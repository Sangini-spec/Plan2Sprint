"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Link2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";

/* ------------------------------------------------------------------ */
/*  Tool definitions                                                   */
/* ------------------------------------------------------------------ */

interface Tool {
  id: string;
  name: string;
  description: string;
  letter: string;
  letterColor: string;
  letterBg: string;
}

const TOOLS: Tool[] = [
  {
    id: "jira",
    name: "Jira",
    description: "Atlassian Jira for issue tracking and agile project management.",
    letter: "J",
    letterColor: "text-[#2684FF]",
    letterBg: "bg-[#2684FF]/10",
  },
  {
    id: "ado",
    name: "Azure DevOps",
    description: "Microsoft Azure DevOps for boards, repos, and pipelines.",
    letter: "A",
    letterColor: "text-[#0078D4]",
    letterBg: "bg-[#0078D4]/10",
  },
  {
    id: "linear",
    name: "Linear",
    description: "Linear for modern, streamlined issue tracking and project cycles.",
    letter: "L",
    letterColor: "text-[#5E6AD2]",
    letterBg: "bg-[#5E6AD2]/10",
  },
  {
    id: "notion",
    name: "Notion",
    description: "Notion databases for flexible backlog and sprint management.",
    letter: "N",
    letterColor: "text-[#191919] dark:text-[#FFFFFF]",
    letterBg: "bg-[#191919]/10 dark:bg-[#FFFFFF]/10",
  },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function ConnectToolStep({ onNext }: { onNext: () => void }) {
  const [selectedTool, setSelectedTool] = useState<string | null>(null);

  return (
    <div className="flex flex-col items-center text-center">
      {/* Header */}
      <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--color-brand-secondary)]/10">
        <Link2 className="h-6 w-6 text-[var(--color-brand-secondary)]" />
      </div>

      <h2 className="mt-4 text-2xl font-bold text-[var(--text-primary)]">
        Connect Your Project Management Tool
      </h2>
      <p className="mt-2 max-w-lg text-sm text-[var(--text-secondary)]">
        Link your Jira, Azure DevOps, Linear, or Notion workspace so Plan2Sprint
        can read your backlog and sprint data.
      </p>

      {/* Tool Grid */}
      <div className="mt-8 grid w-full max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
        {TOOLS.map((tool) => {
          const isSelected = selectedTool === tool.id;

          return (
            <motion.button
              key={tool.id}
              type="button"
              whileHover={{ y: -2 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => setSelectedTool(tool.id)}
              className={cn(
                "relative flex flex-col items-start gap-3 rounded-2xl border p-5 text-left transition-all duration-200 cursor-pointer",
                "bg-[var(--bg-surface)] hover:bg-[var(--bg-surface-raised)]",
                isSelected
                  ? "border-[var(--color-brand-secondary)] shadow-lg shadow-[var(--color-brand-secondary)]/10"
                  : "border-[var(--border-subtle)]"
              )}
            >
              {/* Selection indicator */}
              {isSelected && (
                <motion.div
                  layoutId="tool-selection"
                  className="absolute inset-0 rounded-2xl border-2 border-[var(--color-brand-secondary)] pointer-events-none"
                  transition={{ type: "spring", stiffness: 300, damping: 30 }}
                />
              )}

              {/* Icon */}
              <div
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-xl text-lg font-bold",
                  tool.letterBg,
                  tool.letterColor
                )}
              >
                {tool.letter}
              </div>

              {/* Text */}
              <div>
                <p className="text-sm font-semibold text-[var(--text-primary)]">
                  {tool.name}
                </p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  {tool.description}
                </p>
              </div>

              {/* Connect label */}
              <span
                className={cn(
                  "mt-auto inline-flex items-center gap-1 text-xs font-medium",
                  isSelected
                    ? "text-[var(--color-brand-secondary)]"
                    : "text-[var(--text-secondary)]"
                )}
              >
                {isSelected ? "Selected" : "Connect"}
              </span>
            </motion.button>
          );
        })}
      </div>

      {/* Continue */}
      <Button
        size="lg"
        className="mt-10"
        disabled={!selectedTool}
        onClick={onNext}
      >
        Continue
        <ArrowRight className="h-4 w-4" />
      </Button>
    </div>
  );
}

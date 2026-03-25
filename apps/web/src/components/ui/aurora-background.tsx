"use client";
import { cn } from "@/lib/utils";
import React, { ReactNode } from "react";

interface AuroraBackgroundProps extends React.HTMLProps<HTMLDivElement> {
  children: ReactNode;
  showRadialGradient?: boolean;
}

export const AuroraBackground = ({
  className,
  children,
  showRadialGradient = true,
  ...props
}: AuroraBackgroundProps) => {
  return (
    <div
      className={cn(
        "aurora-bg relative flex flex-col h-full items-center justify-center text-slate-950 transition-bg",
        className
      )}
      {...props}
    >
      <div className="absolute inset-0 overflow-hidden">
        <div
          className={cn(
            "aurora-effect pointer-events-none absolute -inset-[10px] opacity-50 will-change-transform",
            showRadialGradient && "aurora-mask"
          )}
        />
      </div>
      <div className="relative z-10 w-full">
        {children}
      </div>
    </div>
  );
};

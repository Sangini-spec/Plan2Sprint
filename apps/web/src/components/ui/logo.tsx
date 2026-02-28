"use client";

import Image from "next/image";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*  Reusable Logo Component                                                    */
/*  Original logo, no filters, no color changes. Just the image at size.       */
/* -------------------------------------------------------------------------- */

type LogoSize = "sm" | "md" | "lg" | "xl";

interface LogoProps {
  size?: LogoSize;
  className?: string;
  iconOnly?: boolean;
}

const sizeConfig: Record<LogoSize, { width: number; height: number; imgClass: string }> = {
  sm: {
    width: 128,
    height: 128,
    imgClass: "h-16 w-16",
  },
  md: {
    width: 480,
    height: 128,
    imgClass: "h-28 w-auto",
  },
  lg: {
    width: 600,
    height: 160,
    imgClass: "h-36 w-auto",
  },
  xl: {
    width: 720,
    height: 192,
    imgClass: "h-44 w-auto sm:h-48",
  },
};

export function Logo({ size = "md", className, iconOnly = false }: LogoProps) {
  const config = sizeConfig[iconOnly ? "sm" : size];

  return (
    <Image
      src="/logo.png"
      alt="Plan2Sprint"
      width={config.width}
      height={config.height}
      priority={size === "lg" || size === "xl"}
      className={cn(
        "object-contain",
        config.imgClass,
        iconOnly && "object-left",
        className
      )}
    />
  );
}

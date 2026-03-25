"use client";

import Image from "next/image";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

type LogoSize = "sm" | "md" | "sidebar" | "lg" | "xl";

interface LogoProps {
  size?: LogoSize;
  className?: string;
  iconOnly?: boolean;
  /** Force a specific variant regardless of theme */
  variant?: "light" | "dark";
}

const sizeConfig: Record<LogoSize, { width: number; height: number; imgClass: string }> = {
  sm: {
    width: 120,
    height: 120,
    imgClass: "h-8 w-8",
  },
  md: {
    width: 400,
    height: 100,
    imgClass: "h-9 w-auto",
  },
  sidebar: {
    width: 500,
    height: 130,
    imgClass: "w-full h-auto max-w-[140px]",
  },
  lg: {
    width: 700,
    height: 190,
    imgClass: "h-12 w-auto",
  },
  xl: {
    width: 800,
    height: 220,
    imgClass: "h-16 w-auto sm:h-20",
  },
};

const LOGO_LIGHT = "/logo-transparent.png";
const LOGO_DARK = "/Plan2sprint_dark without bg.png";

export function Logo({ size = "md", className, iconOnly = false, variant }: LogoProps) {
  const config = sizeConfig[iconOnly ? "sm" : size];
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // Determine which logo to show
  const isDark = variant ? variant === "dark" : mounted && resolvedTheme === "dark";
  const logoSrc = isDark ? LOGO_DARK : LOGO_LIGHT;

  return (
    <>
      {/* Show both during SSR/hydration to avoid flash, hide one with CSS */}
      {!mounted ? (
        <>
          <Image
            src={LOGO_LIGHT}
            alt="Plan2Sprint"
            width={config.width}
            height={config.height}
            priority={size === "lg" || size === "xl"}
            className={cn(
              "object-contain dark:hidden",
              config.imgClass,
              iconOnly && "object-left",
              className
            )}
          />
          <Image
            src={LOGO_DARK}
            alt="Plan2Sprint"
            width={config.width}
            height={config.height}
            priority={size === "lg" || size === "xl"}
            className={cn(
              "object-contain hidden dark:block",
              config.imgClass,
              iconOnly && "object-left",
              className
            )}
          />
        </>
      ) : (
        <Image
          src={logoSrc}
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
      )}
    </>
  );
}

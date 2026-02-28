"use client";

import React from "react";
import { Shield } from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo } from "@/components/ui/logo";

/* -------------------------------------------------------------------------- */
/*  TYPES                                                                      */
/* -------------------------------------------------------------------------- */

interface FooterLink {
  label: string;
  href: string;
}

interface FooterColumn {
  title: string;
  links: FooterLink[];
}

/* -------------------------------------------------------------------------- */
/*  DATA                                                                       */
/* -------------------------------------------------------------------------- */

const FOOTER_COLUMNS: FooterColumn[] = [
  {
    title: "Product",
    links: [
      { label: "Features", href: "#features" },
      { label: "Solutions", href: "#solutions" },
      { label: "Pricing", href: "#pricing" },
      { label: "Roadmap", href: "#roadmap" },
      { label: "Changelog", href: "#changelog" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About", href: "#about" },
      { label: "Blog", href: "#blog" },
      { label: "Careers", href: "#careers" },
      { label: "Press Kit", href: "#press" },
      { label: "Contact", href: "#contact" },
    ],
  },
  {
    title: "Legal",
    links: [
      { label: "Privacy Policy", href: "#privacy" },
      { label: "Terms of Service", href: "#terms" },
      { label: "Security", href: "#security" },
      { label: "Status", href: "#status" },
      { label: "Documentation", href: "#docs" },
    ],
  },
];

/* -------------------------------------------------------------------------- */
/*  SUB-COMPONENTS                                                             */
/* -------------------------------------------------------------------------- */

function FooterLinkGroup({ title, links }: FooterColumn) {
  return (
    <div>
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/80">
        {title}
      </h3>
      <ul className="space-y-3">
        {links.map((link) => (
          <li key={link.href}>
            <a
              href={link.href}
              className={cn(
                "text-sm text-white/50",
                "transition-colors duration-200",
                "hover:text-[#0D96E6]"
              )}
            >
              {link.label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function GdprBadge() {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full",
        "border border-white/10 bg-white/5",
        "px-3 py-1 text-xs text-white/50"
      )}
    >
      <Shield size={12} className="text-[#22C55E]" />
      <span>GDPR Compliant</span>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  FOOTER (MAIN EXPORT)                                                       */
/* -------------------------------------------------------------------------- */

export function Footer() {
  return (
    <footer className="bg-[#0A0A0F] text-white">
      {/* Top divider gradient */}
      <div className="h-px bg-gradient-to-r from-transparent via-[#0D96E6]/30 to-transparent" />

      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        {/* Main grid */}
        <div className="grid grid-cols-1 gap-12 md:grid-cols-2 lg:grid-cols-5 lg:gap-8">
          {/* Column 1: Brand */}
          <div className="lg:col-span-2">
            {/* Logo with light background container */}
            <a href="/" className="inline-block">
              <Logo size="lg" />
            </a>

            <p className="mt-4 max-w-xs text-sm leading-relaxed text-white/50">
              The planning brain for engineering teams.
            </p>

            {/* Social / newsletter could go here in a future iteration */}
          </div>

          {/* Columns 2-4: Link groups */}
          {FOOTER_COLUMNS.map((column) => (
            <FooterLinkGroup key={column.title} {...column} />
          ))}
        </div>

        {/* Bottom bar */}
        <div
          className={cn(
            "mt-16 flex flex-col items-center justify-between gap-4 border-t border-white/10 pt-8",
            "sm:flex-row"
          )}
        >
          {/* Left: copyright */}
          <p className="text-xs text-white/40">
            &copy; {new Date().getFullYear()} Plan2Sprint. All rights reserved.
          </p>

          {/* Center: tagline */}
          <p className="text-xs text-white/30">
            Made with love for engineering teams
          </p>

          {/* Right: GDPR badge */}
          <GdprBadge />
        </div>
      </div>
    </footer>
  );
}

export default Footer;

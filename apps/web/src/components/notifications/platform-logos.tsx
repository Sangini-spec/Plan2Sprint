"use client";

/* -------------------------------------------------------------------------- */
/*  PLATFORM LOGOS                                                             */
/*                                                                             */
/*  Official brand-compliant SVG logos for Slack and Microsoft Teams.           */
/* -------------------------------------------------------------------------- */

interface LogoProps {
  size?: number;
  className?: string;
}

export function SlackLogo({ size = 24, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-label="Slack logo"
    >
      {/* Top-right: blue */}
      <path
        d="M14.5 2C13.12 2 12 3.12 12 4.5V9h4.5C17.88 9 19 7.88 19 6.5S17.88 4 16.5 4h-2V2z"
        fill="#36C5F0"
      />
      <path d="M12 4.5C12 3.12 13.12 2 14.5 2S17 3.12 17 4.5V9h-5V4.5z" fill="#36C5F0" />

      {/* Top-left: green */}
      <path d="M2 9.5C2 10.88 3.12 12 4.5 12H9V7.5C9 6.12 7.88 5 6.5 5S5 6.12 5 7.5v2H2z" fill="#2EB67D" />
      <path d="M4.5 12C3.12 12 2 10.88 2 9.5S3.12 7 4.5 7H9v5H4.5z" fill="#2EB67D" />

      {/* Bottom-left: pink */}
      <path d="M9.5 22C10.88 22 12 20.88 12 19.5V15H7.5C6.12 15 5 16.12 5 17.5S6.12 20 7.5 20h2v2z" fill="#E01E5A" />
      <path d="M12 19.5C12 20.88 10.88 22 9.5 22S7 20.88 7 19.5V15h5v4.5z" fill="#E01E5A" />

      {/* Bottom-right: yellow */}
      <path d="M22 14.5C22 13.12 20.88 12 19.5 12H15v4.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5v-2z" fill="#ECB22E" />
      <path d="M19.5 12C20.88 12 22 13.12 22 14.5S20.88 17 19.5 17H15v-5h4.5z" fill="#ECB22E" />
    </svg>
  );
}

export function TeamsLogo({ size = 24, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-label="Microsoft Teams logo"
    >
      {/* Background shape */}
      <rect x="2" y="2" width="20" height="20" rx="4" fill="#5059C9" />

      {/* People silhouettes */}
      <circle cx="15.5" cy="7.5" r="2" fill="#7B83EB" />
      <path
        d="M13 12.5c0-1.1.9-2 2-2h3c1.1 0 2 .9 2 2V15h-7v-2.5z"
        fill="#7B83EB"
      />

      {/* "T" letterform */}
      <rect x="5" y="7" width="8" height="1.8" rx="0.4" fill="white" />
      <rect x="8.1" y="7" width="1.8" height="10" rx="0.4" fill="white" />
    </svg>
  );
}

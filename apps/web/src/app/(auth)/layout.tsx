import Link from "next/link";
import { AuthBranding } from "@/components/auth/auth-branding";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="h-screen flex bg-[var(--bg-base)] overflow-hidden">
      {/* Left branding panel */}
      <AuthBranding />

      {/* Right form panel */}
      <div className="flex-1 flex flex-col h-screen">
        {/* Back button */}
        <div className="px-6 pt-4 pb-0">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
            Back
          </Link>
        </div>

        {/* Form area — vertically centered, compact */}
        <div className="flex-1 flex items-center justify-center px-6 py-4 overflow-y-auto">
          <div className="w-full max-w-md">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

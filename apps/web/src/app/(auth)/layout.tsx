import Link from "next/link";
import { Logo } from "@/components/ui/logo";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--bg-base)] px-4 py-12">
      {/* Subtle grid background */}
      <div className="fixed inset-0 grid-pattern opacity-30 pointer-events-none" />

      {/* Logo */}
      <Link href="/" className="relative z-10 mb-8 inline-block">
        <Logo size="xl" />
      </Link>

      {/* Auth card */}
      <div className="relative z-10 w-full max-w-md">
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 backdrop-blur-xl p-8 shadow-xl">
          {children}
        </div>
      </div>

      {/* Footer link */}
      <p className="relative z-10 mt-8 text-sm text-[var(--text-secondary)]">
        <Link
          href="/"
          className="hover:text-[var(--color-brand-secondary)] transition-colors"
        >
          &larr; Back to home
        </Link>
      </p>
    </div>
  );
}

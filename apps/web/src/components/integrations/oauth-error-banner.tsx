"use client";

import { AlertCircle, RefreshCw, X, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

type ErrorType =
  | "oauth_popup_blocked"
  | "oauth_failed"
  | "token_expired"
  | "rate_limited"
  | "csrf_mismatch"
  | "webhook_failed"
  | "network_timeout"
  | "unknown";

const ERROR_CONFIG: Record<
  ErrorType,
  { title: string; description: string; showRetry: boolean; retryLabel?: string }
> = {
  oauth_popup_blocked: {
    title: "Popup Blocked",
    description: "Your browser blocked the OAuth popup. Please allow popups for this site and try again.",
    showRetry: true,
    retryLabel: "Try Again",
  },
  oauth_failed: {
    title: "Authentication Failed",
    description: "The OAuth flow was cancelled or failed. Please try connecting again.",
    showRetry: true,
    retryLabel: "Retry",
  },
  token_expired: {
    title: "Token Expired",
    description: "Your access token has expired. Please re-authenticate to continue syncing.",
    showRetry: true,
    retryLabel: "Re-authenticate",
  },
  rate_limited: {
    title: "Rate Limited",
    description: "Too many requests. Please wait before trying again.",
    showRetry: true,
    retryLabel: "Retry",
  },
  csrf_mismatch: {
    title: "Security Error",
    description: "CSRF token mismatch. Please try the connection again from scratch.",
    showRetry: true,
    retryLabel: "Start Over",
  },
  webhook_failed: {
    title: "Webhook Delivery Failed",
    description: "Failed to process the webhook event. Data may be out of sync.",
    showRetry: true,
    retryLabel: "Retry Sync",
  },
  network_timeout: {
    title: "Connection Timeout",
    description: "The request timed out. Check your network connection and try again.",
    showRetry: true,
    retryLabel: "Retry",
  },
  unknown: {
    title: "Something Went Wrong",
    description: "An unexpected error occurred. Please try again.",
    showRetry: true,
    retryLabel: "Retry",
  },
};

interface OAuthErrorBannerProps {
  errorType: ErrorType;
  retryCountdown?: number; // seconds remaining for rate limit
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export function OAuthErrorBanner({
  errorType,
  retryCountdown,
  onRetry,
  onDismiss,
  className,
}: OAuthErrorBannerProps) {
  const config = ERROR_CONFIG[errorType];

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border p-4",
        "border-[var(--color-rag-red)]/20 bg-[var(--color-rag-red)]/5",
        className
      )}
    >
      <AlertCircle size={18} className="shrink-0 mt-0.5 text-[var(--color-rag-red)]" />

      <div className="flex-1 space-y-2">
        <p className="text-sm font-semibold text-[var(--color-rag-red)]">{config.title}</p>
        <p className="text-xs text-[var(--text-secondary)]">{config.description}</p>

        {config.showRetry && (
          <div className="flex items-center gap-2">
            {retryCountdown && retryCountdown > 0 ? (
              <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                <Clock size={12} />
                Retry in {retryCountdown}s
              </span>
            ) : (
              <button
                onClick={onRetry}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5",
                  "text-xs font-medium",
                  "bg-[var(--color-rag-red)] text-white",
                  "hover:bg-[var(--color-rag-red)]/90",
                  "transition-colors cursor-pointer"
                )}
              >
                <RefreshCw size={12} />
                {config.retryLabel}
              </button>
            )}
          </div>
        )}
      </div>

      {onDismiss && (
        <button
          onClick={onDismiss}
          className="shrink-0 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}

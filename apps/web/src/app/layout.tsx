import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "sonner";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Plan2Sprint - AI Sprint Planning & Async Standups for Engineering Teams",
  description:
    "Plan2Sprint is the AI planning brain for engineering teams - generating sprint plans, daily standups, and retrospectives automatically. From Jira. From GitHub. From real data.",
  keywords: [
    "sprint planning",
    "async standup",
    "AI planning",
    "Jira",
    "GitHub",
    "engineering teams",
    "scrum",
    "agile",
  ],
  openGraph: {
    title: "Plan2Sprint - AI Sprint Planning & Async Standups",
    description:
      "Generate sprint plans and daily standups automatically from Jira, GitHub, and real data.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="bg-[var(--bg-base)] text-[var(--text-primary)] antialiased">
        <ThemeProvider>
          {children}
          <Toaster
            position="bottom-right"
            toastOptions={{
              style: {
                background: "var(--bg-surface)",
                border: "1px solid var(--border-subtle)",
                color: "var(--text-primary)",
              },
            }}
          />
        </ThemeProvider>
      </body>
    </html>
  );
}

"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { AuthProvider } from "@/lib/auth/context";
import { IntegrationProvider } from "@/lib/integrations/context";
import { SelectedProjectProvider } from "@/lib/project/context";
import { WebSocketProvider } from "@/lib/ws/context";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { AppTopbar } from "@/components/layout/app-topbar";
import { ConnectToolsModal } from "@/components/integrations/connect-tools-modal";
import { RouteWarmer } from "@/components/dev/route-warmer";
// Real-time events are processed silently in the backend — no UI toasts needed

const SIDEBAR_WIDTH = 256;
const SIDEBAR_COLLAPSED_WIDTH = 72;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close mobile sidebar on resize to desktop
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 1024) {
        setMobileOpen(false);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  return (
    <AuthProvider>
      <WebSocketProvider>
      <IntegrationProvider>
      <SelectedProjectProvider>
      <div className="flex h-screen overflow-hidden bg-[var(--bg-base)]">
        {/* Desktop sidebar */}
        <div
          className="hidden lg:block shrink-0 transition-all duration-300 ease-out"
          style={{ width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH }}
        >
          <AppSidebar
            collapsed={collapsed}
            onToggle={() => setCollapsed(!collapsed)}
          />
        </div>

        {/* Mobile sidebar overlay */}
        <AnimatePresence>
          {mobileOpen && (
            <>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
                onClick={() => setMobileOpen(false)}
              />
              <motion.div
                initial={{ x: -SIDEBAR_WIDTH }}
                animate={{ x: 0 }}
                exit={{ x: -SIDEBAR_WIDTH }}
                transition={{ type: "spring", damping: 30, stiffness: 300 }}
                className={cn(
                  "fixed inset-y-0 left-0 z-50 lg:hidden"
                )}
                style={{ width: SIDEBAR_WIDTH }}
              >
                <AppSidebar
                  collapsed={false}
                  onToggle={() => setCollapsed(!collapsed)}
                  onMobileClose={() => setMobileOpen(false)}
                />
              </motion.div>
            </>
          )}
        </AnimatePresence>

        {/* Main content area */}
        <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
          <AppTopbar onMenuClick={() => setMobileOpen(!mobileOpen)} />
          <main className="flex-1 overflow-y-auto">
            <div className="p-4 sm:p-6 lg:p-8">
              {children}
            </div>
          </main>
        </div>
      </div>
      <ConnectToolsModal />
      <RouteWarmer />
      </SelectedProjectProvider>
      </IntegrationProvider>
      </WebSocketProvider>
    </AuthProvider>
  );
}

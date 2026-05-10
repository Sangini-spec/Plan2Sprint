"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getSupabase as getSharedSupabase } from "@/lib/supabase/shared-client";
import type { User } from "@supabase/supabase-js";
import type { AppUser, UserRole } from "@/lib/types/auth";
import { setStorageUserId } from "@/lib/integrations/demo-connections";
import { invalidateCache } from "@/lib/fetch-cache";

interface AuthContextType {
  user: User | null;
  appUser: AppUser | null;
  role: UserRole;
  loading: boolean;
  signOut: () => Promise<void>;
  updateAppUser: (updates: Partial<AppUser>) => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  appUser: null,
  role: "developer",
  loading: true,
  signOut: async () => {},
  updateAppUser: () => {},
});

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

// Hotfix 88 — point the local ``getSupabase()`` alias at the shared
// browser singleton in ``lib/supabase/shared-client.ts``. Was a private
// module-level singleton; multiple per-file singletons race-condition
// PKCE on stricter browsers (see shared-client.ts for the postmortem).
function getSupabase() {
  return getSharedSupabase();
}

/** Clear all user-scoped localStorage to prevent cross-user data leakage */
function _clearUserScopedStorage() {
  if (typeof window === "undefined") return;
  const prefixes = [
    "plan2sprint_connections",
    "plan2sprint_integration_audit",
    "plan2sprint_selected_project",
    "plan2sprint_demo_user",
    "plan2sprint_github",
    "plan2sprint_uid",
    "p2s_",
  ];
  const keysToRemove: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && prefixes.some((p) => key.startsWith(p))) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach((k) => localStorage.removeItem(k));
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [appUser, setAppUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Demo mode: read user from localStorage
    if (isDemoMode) {
      try {
        const stored = localStorage.getItem("plan2sprint_demo_user");
        if (stored) {
          const demoUser = JSON.parse(stored);
          setAppUser({
            id: demoUser.id ?? "demo-user-1",
            email: demoUser.email ?? "demo@plan2sprint.app",
            full_name: demoUser.full_name ?? "Demo User",
            avatar_url: undefined,
            role: (demoUser.role as UserRole) ?? "product_owner",
            organization_id: "demo-org",
            organization_name: demoUser.organization_name ?? "Demo Organization",
            onboarding_completed: demoUser.onboarding_completed ?? false,
            created_at: demoUser.created_at ?? new Date().toISOString(),
          });
        } else {
          setAppUser({
            id: "demo-user-1",
            email: "demo@plan2sprint.app",
            full_name: "Demo User",
            avatar_url: undefined,
            role: "product_owner",
            organization_id: "demo-org",
            organization_name: "Demo Organization",
            onboarding_completed: false,
            created_at: new Date().toISOString(),
          });
        }
      } catch {
        setAppUser({
          id: "demo-user-1",
          email: "demo@plan2sprint.app",
          full_name: "Demo User",
          avatar_url: undefined,
          role: "product_owner",
          organization_id: "demo-org",
          organization_name: "Demo Organization",
          onboarding_completed: false,
          created_at: new Date().toISOString(),
        });
      }
      setLoading(false);
      return;
    }

    // Real Supabase auth — use singleton client
    const supabase = getSupabase();

    const getSession = async () => {
      const {
        data: { user: currentUser },
      } = await supabase.auth.getUser();

      setUser(currentUser);

      if (currentUser) {
        // Set per-user storage scope BEFORE any other storage operations
        setStorageUserId(currentUser.id);

        const metadata = currentUser.user_metadata;
        setAppUser({
          id: currentUser.id,
          email: currentUser.email ?? "",
          full_name: metadata?.full_name ?? currentUser.email?.split("@")[0] ?? "User",
          avatar_url: metadata?.avatar_url,
          role: (metadata?.role as UserRole) ?? "product_owner",
          organization_id: metadata?.organization_id ?? "demo-org",
          organization_name: metadata?.organization_name ?? "Demo Organization",
          onboarding_completed: metadata?.onboarding_completed ?? false,
          created_at: currentUser.created_at,
        });
      }

      setLoading(false);
    };

    getSession();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      const prevUserId = user?.id;
      const newUserId = session?.user?.id;

      setUser(session?.user ?? null);

      if (!session?.user) {
        // Sign-out: clear EVERYTHING so the next user starts clean.
        setAppUser(null);
        _clearUserScopedStorage();
        // In-memory fetch cache survives a soft sign-out otherwise — flush it.
        invalidateCache();
        return;
      }

      // Sign-in path. The previous logic only cleared when both prevUserId
      // and newUserId existed AND differed. That missed the common case of
      // user A signing out (prevUserId becomes null) then user B signing
      // in: prevUserId is null so no clear ran, and B inherited A's
      // localStorage scope key + the in-memory fetch cache. Fix: clear on
      // ANY user change, including the null -> userId transition.
      if (prevUserId !== newUserId) {
        _clearUserScopedStorage();
        invalidateCache();
      }

      // Always re-bind the per-user storage scope to the current user.
      // setStorageUserId was only called during the initial getSession, so
      // sign-ins through the listener inherited the previous user's scope.
      if (newUserId) {
        setStorageUserId(newUserId);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const updateAppUser = useCallback((updates: Partial<AppUser>) => {
    setAppUser((prev) => (prev ? { ...prev, ...updates } : prev));
  }, []);

  const signOut = useCallback(async () => {
    // Clear all user-scoped cached data to prevent cross-user leakage
    _clearUserScopedStorage();
    // In-memory fetch cache also persists across sign-outs unless we
    // explicitly invalidate it.
    invalidateCache();

    if (isDemoMode) {
      localStorage.removeItem("plan2sprint_demo_user");
      setAppUser(null);
      setUser(null);
      window.location.href = "/login";
      return;
    }

    const supabase = getSupabase();
    await supabase.auth.signOut();
    setUser(null);
    setAppUser(null);
    // Hard navigation guarantees every React provider re-mounts and every
    // in-memory cache (project context, integrations context, etc.) is
    // dropped. Without this, the next user sees the previous user's state
    // until they manually reload.
    window.location.href = "/login";
  }, []);

  // Hotfix 15 — fallback role when ``appUser`` hasn't populated yet.
  //
  // Was previously "developer", which combined with a brief race in
  // ``DashboardPage`` (where ``loading`` flips false a tick before
  // ``appUser`` is set from the Supabase metadata read) caused EVERY
  // user to be routed to /dev for one render cycle, even POs and
  // stakeholders. The URL got locked in and they never moved.
  //
  // Aligned with line 141 which uses "product_owner" as the appUser
  // default when metadata.role is unset. Two layers, same default —
  // no inconsistency.
  const role: UserRole = appUser?.role ?? "product_owner";

  // Memoize context value to prevent unnecessary child re-renders
  const value = useMemo(
    () => ({ user, appUser, role, loading, signOut, updateAppUser }),
    [user, appUser, role, loading, signOut, updateAppUser]
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

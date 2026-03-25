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
import { createClient } from "@/lib/supabase/client";
import type { User } from "@supabase/supabase-js";
import type { AppUser, UserRole } from "@/lib/types/auth";

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

// Singleton Supabase client — created once, reused across renders
let _supabaseClient: ReturnType<typeof createClient> | null = null;
function getSupabase() {
  if (!_supabaseClient) _supabaseClient = createClient();
  return _supabaseClient;
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
      setUser(session?.user ?? null);
      if (!session?.user) {
        setAppUser(null);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const updateAppUser = useCallback((updates: Partial<AppUser>) => {
    setAppUser((prev) => (prev ? { ...prev, ...updates } : prev));
  }, []);

  const signOut = useCallback(async () => {
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
  }, []);

  const role: UserRole = appUser?.role ?? "developer";

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

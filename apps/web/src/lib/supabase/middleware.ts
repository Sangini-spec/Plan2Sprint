import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

/** Routes that require authentication - only these call getUser() */
const PROTECTED_PREFIXES = [
  "/dashboard",
  "/po",
  "/dev",
  "/stakeholder",
  "/settings",
  "/onboarding",
];

function isProtectedRoute(pathname: string) {
  return PROTECTED_PREFIXES.some((p) => pathname.startsWith(p));
}

// Hotfix 58 (HIGH-11) - role-based route segregation.
//
// Each role has a set of route prefixes it's allowed to render. If a
// caller tries to navigate to a prefix outside their allowlist, we
// redirect them to their default landing page. This is a UX-grade
// defence-in-depth check - server-side endpoints already gate
// mutations via require_po / require_write_role (Hotfixes 51 / 55 /
// 56), so a sneaky user bypassing this client-side guard still can't
// actually mutate data they shouldn't.
//
// `/dashboard`, `/settings`, `/onboarding`, `/profile` are allowed for
// every authenticated role.
const ROLE_ROUTE_RULES: Record<string, string[]> = {
  product_owner: ["/po", "/dev", "/stakeholder", "/dashboard", "/settings", "/onboarding"],
  admin: ["/po", "/dev", "/stakeholder", "/dashboard", "/settings", "/onboarding"],
  owner: ["/po", "/dev", "/stakeholder", "/dashboard", "/settings", "/onboarding"],
  developer: ["/dev", "/dashboard", "/settings", "/onboarding"],
  engineering_manager: ["/dev", "/po", "/dashboard", "/settings", "/onboarding"],
  stakeholder: ["/stakeholder", "/dashboard", "/settings", "/onboarding"],
};

const ROLE_DEFAULT_LANDING: Record<string, string> = {
  product_owner: "/po",
  admin: "/po",
  owner: "/po",
  developer: "/dev",
  engineering_manager: "/dev",
  stakeholder: "/stakeholder",
};

function isAllowedForRole(role: string | undefined, pathname: string): boolean {
  if (!role) return false;
  const allowed = ROLE_ROUTE_RULES[role.toLowerCase()];
  if (!allowed) return false;
  return allowed.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

export async function updateSession(request: NextRequest) {
  // Demo mode - skip everything
  if (isDemoMode) {
    return NextResponse.next({ request });
  }

  const { pathname } = request.nextUrl;

  // ── Only protected routes call Supabase. Everything else passes through instantly. ──
  if (!isProtectedRoute(pathname)) {
    return NextResponse.next({ request });
  }

  // ── Protected route: verify auth via Supabase getUser() ──
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  // Not authenticated - redirect to login
  if (!user) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  // Hotfix 58 (HIGH-11) - role-gate the protected routes. Roles come
  // from Supabase user_metadata (set at signup / by admin). This is a
  // soft check; the API still enforces role on every mutation.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const role = (user.user_metadata as any)?.role?.toLowerCase?.() || "";
  if (role && !isAllowedForRole(role, pathname)) {
    const landing = ROLE_DEFAULT_LANDING[role] || "/dashboard";
    // Avoid redirect loop: only redirect if we're not already on the landing.
    if (!pathname.startsWith(landing)) {
      const url = request.nextUrl.clone();
      url.pathname = landing;
      return NextResponse.redirect(url);
    }
  }

  return supabaseResponse;
}

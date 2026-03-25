export type UserRole =
  | "owner"
  | "admin"
  | "product_owner"
  | "engineering_manager"
  | "developer"
  | "stakeholder";

export interface AppUser {
  id: string;
  email: string;
  full_name: string;
  avatar_url?: string;
  role: UserRole;
  organization_id: string;
  organization_name: string;
  onboarding_completed: boolean;
  created_at: string;
}

export const ROLE_LABELS: Record<UserRole, string> = {
  owner: "Owner",
  admin: "Admin",
  product_owner: "Product Owner",
  engineering_manager: "Engineering Manager",
  developer: "Developer",
  stakeholder: "Stakeholder",
};

export const ROLE_DASHBOARD_ROUTES: Record<UserRole, string> = {
  owner: "/po",
  admin: "/po",
  product_owner: "/po",
  engineering_manager: "/po",
  developer: "/dev",
  stakeholder: "/stakeholder",
};

/** Roles that can access the PO dashboard */
export const PO_DASHBOARD_ROLES: UserRole[] = [
  "owner",
  "admin",
  "product_owner",
  "engineering_manager",
];

/** Roles that can access the Developer dashboard */
export const DEV_DASHBOARD_ROLES: UserRole[] = [
  "owner",
  "admin",
  "developer",
];

/** Check if role has management access (owner, admin, or product_owner) */
export function isAdmin(role: UserRole | string | undefined): boolean {
  return role === "owner" || role === "admin" || role === "product_owner";
}

/** Roles that can access the Stakeholder dashboard */
export const STAKEHOLDER_DASHBOARD_ROLES: UserRole[] = [
  "owner",
  "admin",
  "product_owner",
  "engineering_manager",
  "stakeholder",
];

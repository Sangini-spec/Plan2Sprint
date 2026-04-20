"use client";

import { useEffect } from "react";

/**
 * Dev-only component that warms up all app routes in the background.
 * Webpack compiles pages on-demand in dev mode, causing slow first loads.
 * This silently fetches every route so they're pre-compiled before the user clicks.
 */

const APP_ROUTES = [
  "/po",
  "/po/planning",
  "/po/standups",
  "/po/health",
  "/po/retro",
  "/po/github",
  "/po/projects",
  "/po/notifications",
  "/dev",
  "/dev/standup",
  "/dev/sprint",
  "/dev/github",
  "/dev/projects",
  "/dev/notifications",
  "/stakeholder",
  "/stakeholder/health",
  "/stakeholder/delivery",
  "/stakeholder/epics",
  "/stakeholder/standups",
  "/stakeholder/export",
  "/settings",
  "/settings/team",
  "/settings/connections",
  "/settings/notifications",
  "/login",
  "/signup",
];

export function RouteWarmer() {
  // Disabled: route warming fetches 28 pages on startup, competing with
  // actual page loads and adding ~8s of network activity.
  // Pages compile on-demand fast enough with Next.js 15 Turbopack.
  return null;
}

"use client";

import { useState, useEffect, useCallback, useRef } from "react";

/* -------------------------------------------------------------------------- */
/*  CHANNEL CONNECTION STATUS HOOK                                              */
/*                                                                              */
/*  Fetches real connection status from the backend for Slack / Teams.          */
/*  Also handles URL search params from OAuth callback redirects.              */
/*                                                                              */
/*  Hotfix 73/74 - accepts a ``mode``:                                          */
/*    "org" - calls /api/integrations/{slack,teams}/status (PO view).          */
/*    "me"  - calls /api/integrations/{slack,teams}/me/status (per-user view). */
/*  The shared ``ChannelStatus`` shape carries either                           */
/*  team_name (org mode) or linkedAs handle/displayName (me mode).              */
/* -------------------------------------------------------------------------- */

export type ChannelState = "loading" | "disconnected" | "connected" | "error";
export type ChannelStatusMode = "org" | "me";

export interface ChannelStatus {
  state: ChannelState;
  teamName: string;
  connectedAt: string | null;
  scope: string;
  error: string | null;
  tokenExpired?: boolean;
  /** Hotfix 73/74 - set in ``mode: "me"``: the dev's @handle / display name */
  linkedAs?: string;
}

export interface UseChannelStatusReturn {
  slack: ChannelStatus;
  teams: ChannelStatus;
  refreshStatus: () => void;
  isLoading: boolean;
}

const DEFAULT_STATUS: ChannelStatus = {
  state: "loading",
  teamName: "",
  connectedAt: null,
  scope: "",
  error: null,
};

export function useChannelStatus(
  mode: ChannelStatusMode = "org"
): UseChannelStatusReturn {
  const [slack, setSlack] = useState<ChannelStatus>(DEFAULT_STATUS);
  const [teams, setTeams] = useState<ChannelStatus>(DEFAULT_STATUS);

  // Track which channels were set via URL params so we don't overwrite them
  const slackFromParams = useRef(false);
  const teamsFromParams = useRef(false);

  const fetchSlackStatus = useCallback(async () => {
    const url =
      mode === "me"
        ? "/api/integrations/slack/me/status"
        : "/api/integrations/slack/status";
    try {
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        if (mode === "me") {
          setSlack({
            state: data.linked ? "connected" : "disconnected",
            teamName: data.slack_team_name || "",
            connectedAt: null,
            scope: "",
            error: null,
            linkedAs: data.slack_handle || data.slack_user_id || "",
          });
        } else {
          setSlack({
            state: data.connected ? "connected" : "disconnected",
            teamName: data.team_name || "",
            connectedAt: data.connected_at || null,
            scope: data.scope || "",
            error: null,
          });
        }
      } else {
        setSlack({ ...DEFAULT_STATUS, state: "disconnected" });
      }
    } catch {
      setSlack({ ...DEFAULT_STATUS, state: "disconnected" });
    }
  }, [mode]);

  const fetchTeamsStatus = useCallback(async () => {
    const url =
      mode === "me"
        ? "/api/integrations/teams/me/status"
        : "/api/integrations/teams/status";
    try {
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        if (mode === "me") {
          setTeams({
            state: data.linked ? "connected" : "disconnected",
            teamName: "",
            connectedAt: null,
            scope: "",
            error: null,
            linkedAs:
              data.teams_display_name ||
              data.teams_user_principal_name ||
              data.teams_user_id ||
              "",
          });
        } else {
          setTeams({
            state: data.connected ? "connected" : "disconnected",
            teamName: data.tenant_name || "",
            connectedAt: data.connected_at || null,
            scope: data.scope || "",
            error: null,
            tokenExpired: data.token_expired,
          });
        }
      } else {
        setTeams({ ...DEFAULT_STATUS, state: "disconnected" });
      }
    } catch {
      setTeams({ ...DEFAULT_STATUS, state: "disconnected" });
    }
  }, [mode]);

  const fetchStatus = useCallback(() => {
    fetchSlackStatus();
    fetchTeamsStatus();
  }, [fetchSlackStatus, fetchTeamsStatus]);

  // Check URL params for OAuth callback results + fetch remaining statuses
  useEffect(() => {
    if (typeof window === "undefined") return;

    const params = new URLSearchParams(window.location.search);

    // Hotfix 73 - per-user Slack OAuth callback (slack_me=linked|error|demo_linked)
    const slackMeParam = params.get("slack_me");
    if (slackMeParam === "linked" || slackMeParam === "demo_linked") {
      slackFromParams.current = true;
      fetchSlackStatus(); // re-fetch /me/status to pick up the new linkedAs
      const url = new URL(window.location.href);
      url.searchParams.delete("slack_me");
      url.searchParams.delete("detail");
      window.history.replaceState({}, "", url.pathname);
    } else if (slackMeParam === "error") {
      const detail = params.get("detail") || "Unknown error";
      setSlack({
        state: "error",
        teamName: "",
        connectedAt: null,
        scope: "",
        error: detail,
      });
      slackFromParams.current = true;
      const url = new URL(window.location.href);
      url.searchParams.delete("slack_me");
      url.searchParams.delete("detail");
      window.history.replaceState({}, "", url.pathname);
    }

    // Hotfix 74 - per-user Teams OAuth callback
    const teamsMeParam = params.get("teams_me");
    if (teamsMeParam === "linked" || teamsMeParam === "demo_linked") {
      teamsFromParams.current = true;
      fetchTeamsStatus();
      const url = new URL(window.location.href);
      url.searchParams.delete("teams_me");
      url.searchParams.delete("detail");
      window.history.replaceState({}, "", url.pathname);
    } else if (teamsMeParam === "error") {
      const detail = params.get("detail") || "Unknown error";
      setTeams({
        state: "error",
        teamName: "",
        connectedAt: null,
        scope: "",
        error: detail,
      });
      teamsFromParams.current = true;
      const url = new URL(window.location.href);
      url.searchParams.delete("teams_me");
      url.searchParams.delete("detail");
      window.history.replaceState({}, "", url.pathname);
    }

    // Slack callback
    const slackParam = params.get("slack");
    if (slackParam === "connected" || slackParam === "demo_connected") {
      const teamName = params.get("team") || "";
      setSlack({
        state: "connected",
        teamName,
        connectedAt: new Date().toISOString(),
        scope: "",
        error: null,
      });
      slackFromParams.current = true;
      // Clean URL params
      const url = new URL(window.location.href);
      url.searchParams.delete("slack");
      url.searchParams.delete("team");
      window.history.replaceState({}, "", url.pathname);
    } else if (slackParam === "error") {
      const detail = params.get("detail") || "Unknown error";
      setSlack({
        state: "error",
        teamName: "",
        connectedAt: null,
        scope: "",
        error: detail,
      });
      slackFromParams.current = true;
      const url = new URL(window.location.href);
      url.searchParams.delete("slack");
      url.searchParams.delete("detail");
      window.history.replaceState({}, "", url.pathname);
    }

    // Teams callback
    const teamsParam = params.get("teams");
    if (teamsParam === "connected" || teamsParam === "demo_connected") {
      const orgName = params.get("org") || "";
      setTeams({
        state: "connected",
        teamName: orgName,
        connectedAt: new Date().toISOString(),
        scope: "",
        error: null,
      });
      teamsFromParams.current = true;
      const url = new URL(window.location.href);
      url.searchParams.delete("teams");
      url.searchParams.delete("org");
      window.history.replaceState({}, "", url.pathname);
    } else if (teamsParam === "error") {
      const detail = params.get("detail") || "Unknown error";
      setTeams({
        state: "error",
        teamName: "",
        connectedAt: null,
        scope: "",
        error: detail,
      });
      teamsFromParams.current = true;
      const url = new URL(window.location.href);
      url.searchParams.delete("teams");
      url.searchParams.delete("detail");
      window.history.replaceState({}, "", url.pathname);
    }

    // Hotfix 73/74 - always fetch status from API on mount AND when
    // ``mode`` changes (i.e. when auth context lazily resolves the
    // user's role). Without this unconditional fetch, a non-PO whose
    // role takes a tick to load would have ``mode`` flip from "org"
    // to "me" AFTER the URL-param branch already set ``fromParams=
    // true``, and the second effect run would skip the fetch entirely
    // - leaving the card stuck on whatever ``/status`` returned (which
    // is ``connected: false`` for non-PO post-Hotfix 72). The URL
    // param branch above is for optimistic UX during the OAuth
    // round-trip; the server fetch is the source of truth.
    fetchSlackStatus();
    fetchTeamsStatus();
  }, [fetchSlackStatus, fetchTeamsStatus]);

  const isLoading = slack.state === "loading" || teams.state === "loading";

  return { slack, teams, refreshStatus: fetchStatus, isLoading };
}

"use client";

import { useState, useEffect, useCallback, useRef } from "react";

/* -------------------------------------------------------------------------- */
/*  CHANNEL CONNECTION STATUS HOOK                                              */
/*                                                                              */
/*  Fetches real connection status from the backend for Slack / Teams.          */
/*  Also handles URL search params from OAuth callback redirects.              */
/* -------------------------------------------------------------------------- */

export type ChannelState = "loading" | "disconnected" | "connected" | "error";

export interface ChannelStatus {
  state: ChannelState;
  teamName: string;
  connectedAt: string | null;
  scope: string;
  error: string | null;
  tokenExpired?: boolean;
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

export function useChannelStatus(): UseChannelStatusReturn {
  const [slack, setSlack] = useState<ChannelStatus>(DEFAULT_STATUS);
  const [teams, setTeams] = useState<ChannelStatus>(DEFAULT_STATUS);

  // Track which channels were set via URL params so we don't overwrite them
  const slackFromParams = useRef(false);
  const teamsFromParams = useRef(false);

  const fetchSlackStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/integrations/slack/status");
      if (res.ok) {
        const data = await res.json();
        setSlack({
          state: data.connected ? "connected" : "disconnected",
          teamName: data.team_name || "",
          connectedAt: data.connected_at || null,
          scope: data.scope || "",
          error: null,
        });
      } else {
        setSlack({ ...DEFAULT_STATUS, state: "disconnected" });
      }
    } catch {
      setSlack({ ...DEFAULT_STATUS, state: "disconnected" });
    }
  }, []);

  const fetchTeamsStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/integrations/teams/status");
      if (res.ok) {
        const data = await res.json();
        setTeams({
          state: data.connected ? "connected" : "disconnected",
          teamName: data.tenant_name || "",
          connectedAt: data.connected_at || null,
          scope: data.scope || "",
          error: null,
          tokenExpired: data.token_expired,
        });
      } else {
        setTeams({ ...DEFAULT_STATUS, state: "disconnected" });
      }
    } catch {
      setTeams({ ...DEFAULT_STATUS, state: "disconnected" });
    }
  }, []);

  const fetchStatus = useCallback(() => {
    fetchSlackStatus();
    fetchTeamsStatus();
  }, [fetchSlackStatus, fetchTeamsStatus]);

  // Check URL params for OAuth callback results + fetch remaining statuses
  useEffect(() => {
    if (typeof window === "undefined") return;

    const params = new URLSearchParams(window.location.search);

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

    // Fetch status from API for channels NOT already set by URL params
    if (!slackFromParams.current) {
      fetchSlackStatus();
    }
    if (!teamsFromParams.current) {
      fetchTeamsStatus();
    }
  }, [fetchSlackStatus, fetchTeamsStatus]);

  const isLoading = slack.state === "loading" || teams.state === "loading";

  return { slack, teams, refreshStatus: fetchStatus, isLoading };
}

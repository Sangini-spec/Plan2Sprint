"use client";

import { useState, useEffect } from "react";
import { MyNotificationInbox } from "@/components/dev/my-notification-inbox";
import { DeliveryChannelsSection } from "@/components/notifications/delivery-channels-section";
import { SlackQuickActions } from "@/components/notifications/slack-quick-actions";
import { SlackMessageComposer } from "@/components/notifications/slack-message-composer";

export default function NotificationsPage() {
  const [slackConnected, setSlackConnected] = useState(false);
  const [teamsConnected, setTeamsConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function checkConnections() {
      // Check Slack
      try {
        const res = await fetch("/api/integrations/slack/status");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setSlackConnected(data.connected === true);
        }
      } catch {
        // Ignore
      }

      // Check Teams
      try {
        const res = await fetch("/api/integrations/teams/status");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setTeamsConnected(data.connected === true);
        }
      } catch {
        // Ignore
      }
    }

    checkConnections();
    return () => { cancelled = true; };
  }, []);

  const anyChannelConnected = slackConnected || teamsConnected;

  return (
    <div className="space-y-8">
      <MyNotificationInbox />
      <DeliveryChannelsSection />

      {/* Quick actions & composer — when any channel is connected */}
      {anyChannelConnected && (
        <>
          <SlackQuickActions role="dev" />
          {slackConnected && <SlackMessageComposer />}
        </>
      )}
    </div>
  );
}

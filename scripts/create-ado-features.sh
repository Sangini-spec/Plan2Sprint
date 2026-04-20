#!/usr/bin/env bash
# Phase 2: create post-pilot Features + extra Stories, then parent all 17
# child User Stories (my 11 existing + 6 new ones) under the 5 new Features.
#
# Assumes these existing orphan User Stories already exist (from phase 1):
#   2714 Microsoft Teams channel parity with Slack
#   2715 Blocker Escalate / Resolve buttons in Slack
#   2716 Smart Notes - sticky-note drawer
#   2717 Stakeholder dashboard redesign
#   2718 Velocity trend - three-tier fallback
#   2719 Weekly stakeholder PDF report
#   2720 Weekly PDF polish
#   2721 Data integrity - repair orphan iteration links
#   2722 UI polish
#   2723 Fix automated digest scheduling when ACA scales to zero
#   2724 Weekly PDF - graceful empty-project edge cases

set -euo pipefail

ORG=https://dev.azure.com/Concept2Action
PROJECT=Plan2Sprint
AREA="Plan2Sprint"

# --- helper: create a work item, return just its id ---------------
create_item() {
  local TYPE="$1" TITLE="$2"
  az boards work-item create \
    --organization "$ORG" --project "$PROJECT" \
    --type "$TYPE" --title "$TITLE" --area "$AREA" \
    --output tsv --query "id" 2>/dev/null | tr -d '\r' | tr -d '[:space:]'
}

# --- helper: update description, state, tags --------------------
update_item() {
  local ID="$1" STATE="$2" TAGS="$3" DESC="$4"
  az boards work-item update --id "$ID" \
    --organization "$ORG" \
    --description "$DESC" \
    --state "$STATE" \
    --fields "System.Tags=$TAGS" \
    --output none 2>/dev/null
}

# --- helper: add parent link -----------------------------------
link_parent() {
  local CHILD="$1" PARENT="$2"
  az boards work-item relation add --id "$CHILD" \
    --relation-type parent \
    --target-id "$PARENT" \
    --organization "$ORG" \
    --output none 2>/dev/null
}

# ============================================================
# 1) Create 5 new Features
# ============================================================
echo "=== Creating 5 Features ==="

FEAT_TEAMS=$(create_item "Feature" "Microsoft Teams Parity with Slack")
echo "  $FEAT_TEAMS  Microsoft Teams Parity with Slack"
update_item "$FEAT_TEAMS" "Resolved" "post-pilot; teams; slack; integrations" \
"Post-pilot umbrella for reaching functional parity between Microsoft Teams and Slack. Adds channel auto-creation inside a chosen parent MS Team, a platform tab switcher on PO + Dev Channels + Standup pages, HMAC-signed Adaptive Cards for bot-free flows, and Teams-flavoured templates for standup, blocker, announcement and sprint plan messages."

FEAT_NOTES=$(create_item "Feature" "Smart Notes")
echo "  $FEAT_NOTES  Smart Notes"
update_item "$FEAT_NOTES" "Resolved" "post-pilot; notes; ai" \
"Post-pilot collaboration feature — a per-user private sticky-note drawer for Product Owners and Developers. Supports full CRUD, AI Expand (Grok-4) that rewrites rough ideas into structured proposals, and one-click share to a project's Slack or Teams channel. Stakeholder role intentionally excluded per product requirement."

FEAT_STAKE=$(create_item "Feature" "Stakeholder Dashboard Revamp")
echo "  $FEAT_STAKE  Stakeholder Dashboard Revamp"
update_item "$FEAT_STAKE" "Resolved" "post-pilot; stakeholder; dashboard" \
"Post-pilot overhaul of the stakeholder overview after feedback that the dashboard felt empty and per-iteration cards were noisy. New layout: Sprint Completion hero (Actual vs Expected vs Delta% + Predictability), three gradient section cards (Delivery / Epics / Team Health), velocity trend with three-tier fallback, Top Risks + Upcoming Milestones panels, humanised overdue labels and delta caps to prevent absurd percentages."

FEAT_PDF=$(create_item "Feature" "Weekly Stakeholder PDF Report")
echo "  $FEAT_PDF  Weekly Stakeholder PDF Report"
update_item "$FEAT_PDF" "Active" "post-pilot; reports; pdf" \
"Post-pilot reporting channel — a one-page landscape A4 PDF automatically emailed to every project's assigned stakeholders every Friday at 5:00 PM IST, and also downloadable on demand from the Export dashboard. Built with reportlab. Includes semicircle completion gauge, project timeline bar, Team Health / Progress / Risks cards and Upcoming Milestones strip. SMTP delivery via the existing Google App-password setup."

FEAT_REL=$(create_item "Feature" "Platform Reliability and Data Integrity")
echo "  $FEAT_REL  Platform Reliability and Data Integrity"
update_item "$FEAT_REL" "Active" "post-pilot; infra; data-fix" \
"Covers post-pilot hardening work that keeps Plan2Sprint quietly doing the right thing in production: repairing orphan foreign-key references exposed during the pilot (e.g. work_items pointing at deleted iterations) and fixing the ACA scale-to-zero problem that silently skipped scheduled Slack and Teams digests. Ongoing — some items still open."

# ============================================================
# 2) Create 6 new User Stories (children of the new Features)
# ============================================================
echo ""
echo "=== Creating 6 new User Stories ==="

STORY_TABS=$(create_item "User Story" "Platform tab switcher on PO and Dev channels + standup pages")
echo "  $STORY_TABS  Platform tab switcher"
update_item "$STORY_TABS" "Resolved" "post-pilot; teams; slack; ui" \
"New apps/web/src/components/notifications/platform-tabs.tsx. Tab bar shows [Slack] [Teams] with smart default — persists last selection in localStorage, otherwise falls back to whichever platform the org has connected. All downstream buttons (quick actions, message composer, blocker sender, standup 'Send to ...' buttons) branch on the active tab and call the platform-specific endpoint."

STORY_AIEXPAND=$(create_item "User Story" "AI Expand - Grok-4 rewrites rough notes into structured proposals")
echo "  $STORY_AIEXPAND  AI Expand"
update_item "$STORY_AIEXPAND" "Resolved" "post-pilot; notes; ai" \
"Grok-4-fast-reasoning prompt that takes a short note the PO jotted (often a bullet or two of an idea) and returns a well-structured proposal suitable for sharing: problem framing, 3-5 key bullets, a clear next step. Triggered from a gradient 'Expand' button inside the note drawer. Streams back tokens for a smooth feel."

STORY_NOTE_SHARE=$(create_item "User Story" "Share note to project Slack or Teams channel")
echo "  $STORY_NOTE_SHARE  Share note to channel"
update_item "$STORY_NOTE_SHARE" "Resolved" "post-pilot; notes; slack; teams" \
"From any note, one-click send to the active project's Slack channel (proj-{name}) or Teams channel. Author attribution and timestamp included. Honours the platform tab switcher so PO can choose destination. Uses the existing post-to-channel endpoints from the Teams parity work."

STORY_DELTA=$(create_item "User Story" "Humanised overdue labels and delta caps on stakeholder dashboard")
echo "  $STORY_DELTA  Humanised labels + caps"
update_item "$STORY_DELTA" "Resolved" "post-pilot; stakeholder; dashboard" \
"Small but user-visible polish: labels like 'in -28d' became '28d overdue'; cross-unit velocity comparisons capped at +/-500% so an item-count sprint followed by a story-point sprint no longer produces +19200% delta readouts. Applied on Sprint Completion hero + Velocity Trend tiles."

STORY_SMTP=$(create_item "User Story" "SMTP PDF attachment delivery via Google App password")
echo "  $STORY_SMTP  SMTP attachment delivery"
update_item "$STORY_SMTP" "Resolved" "post-pilot; reports; pdf; email" \
"Extended apps/api/app/email/sender.py with send_report_email(to, subject, html, pdf_bytes, pdf_filename) — reuses the existing Google App-password SMTP executor and builds a MIMEApplication PDF attachment with Content-Disposition: attachment. Handles the Friday Weekly Report email fan-out per stakeholder."

STORY_VERIFY=$(create_item "User Story" "Re-verify all weekly scheduler ticks fire after min-replicas change")
echo "  $STORY_VERIFY  Verify scheduler ticks"
update_item "$STORY_VERIFY" "New" "planned; infra; scheduling; qa" \
"After the 'Fix automated digest scheduling when ACA scales to zero' story lands (min-replicas=1 or external cron), watch two consecutive weeks in production: (1) 9 AM IST morning digests fire for every connected org; (2) 5 PM IST evening summaries fire; (3) 5 PM IST Friday weekly PDF email lands in every assigned stakeholder inbox; (4) in-app notifications appear. Track in a spreadsheet, close when two weeks clean."

# ============================================================
# 3) Parent links: 17 child stories -> 5 parent Features
# ============================================================
echo ""
echo "=== Linking child User Stories to parent Features ==="

declare -A LINKS=(
  # Teams Parity (FEAT_TEAMS)
  ["2714"]="$FEAT_TEAMS"
  ["2715"]="$FEAT_TEAMS"
  ["$STORY_TABS"]="$FEAT_TEAMS"

  # Smart Notes (FEAT_NOTES)
  ["2716"]="$FEAT_NOTES"
  ["$STORY_AIEXPAND"]="$FEAT_NOTES"
  ["$STORY_NOTE_SHARE"]="$FEAT_NOTES"

  # Stakeholder Dashboard Revamp (FEAT_STAKE)
  ["2717"]="$FEAT_STAKE"
  ["2718"]="$FEAT_STAKE"
  ["2722"]="$FEAT_STAKE"
  ["$STORY_DELTA"]="$FEAT_STAKE"

  # Weekly Stakeholder PDF Report (FEAT_PDF)
  ["2719"]="$FEAT_PDF"
  ["2720"]="$FEAT_PDF"
  ["2724"]="$FEAT_PDF"
  ["$STORY_SMTP"]="$FEAT_PDF"

  # Platform Reliability & Data Integrity (FEAT_REL)
  ["2721"]="$FEAT_REL"
  ["2723"]="$FEAT_REL"
  ["$STORY_VERIFY"]="$FEAT_REL"
)

for CHILD in "${!LINKS[@]}"; do
  PARENT="${LINKS[$CHILD]}"
  echo "  linking  story $CHILD -> feature $PARENT"
  link_parent "$CHILD" "$PARENT" || echo "    WARN: link failed for $CHILD"
done

echo ""
echo "=== Done ==="
echo "New Features: $FEAT_TEAMS $FEAT_NOTES $FEAT_STAKE $FEAT_PDF $FEAT_REL"
echo "New Stories:  $STORY_TABS $STORY_AIEXPAND $STORY_NOTE_SHARE $STORY_DELTA $STORY_SMTP $STORY_VERIFY"

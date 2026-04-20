#!/usr/bin/env bash
# Create Plan2Sprint post-pilot + planned backlog items in ADO.
# Idempotency is NOT handled here — re-running will create duplicates.
# Run once from a machine with `az` + `az devops` extension configured.

set -euo pipefail

ORG=https://dev.azure.com/Concept2Action
PROJECT=Plan2Sprint
AREA="Plan2Sprint"

# One row per work item: TITLE|STATE|TAGS|DESCRIPTION
# Description is plain text (no HTML) — ADO converts newlines to <br/>.
ITEMS=(
  "Blocker Escalate / Resolve buttons in Slack|Resolved|post-pilot; slack; blockers|Interactive action buttons on every blocker notification posted to Slack. Dev clicks Escalate -> blocker status flips to ESCALATED and notifies the EM; clicks Resolve -> status flips to RESOLVED and the card updates in-place. Uses action_id + HMAC signature verification so the payload cannot be spoofed. Simpler than the original over-built escalation flow (rolled back EM + stakeholder fan-out)."
  "Smart Notes - sticky-note drawer with AI Expand and channel sharing|Resolved|post-pilot; notes; ai|Per-user private notes drawer accessible from a gradient button in the topbar. Features: sticky-note card layout, AI Expand (Grok-4) that rewrites rough ideas into structured proposals, share-to-Slack-or-Teams channel button, full CRUD. Theme-aware drawer background (fixes transparency in dark + light mode). Access restricted to Product Owner and Developer roles only - stakeholders do not see the button."
  "Stakeholder dashboard redesign - Sprint Completion hero and section cards|Resolved|post-pilot; stakeholder; dashboard|Removed per-iteration cards and rebuilt stakeholder overview with: (1) Sprint Completion hero showing Actual vs Expected vs Delta% + Predictability score; (2) three gradient section cards (Delivery / Epics / Team Health) each with its own metric group + conclusion sentence; (3) Velocity Trend chart; (4) Top Risks + Upcoming Milestones side-by-side panels. Asymmetric 12-col grid (8:4, 7:5 golden ratios)."
  "Velocity trend - three-tier fallback with per-sprint unit selection|Resolved|post-pilot; velocity; stakeholder|Velocity chart no longer shows empty state when a project has no story-point estimates. Tier 1: use backend sustainability trend. Tier 2: sprints with SP. Tier 3: sprints with item-counts. Per-sprint unit selection (SP preferred, items fallback). Delta-vs-last cap at +/-500% to kill absurd cross-unit 19200% readouts. Humanized overdue labels (28d overdue instead of in -28d)."
  "Weekly stakeholder PDF report - Friday 5 PM IST auto-email + on-demand download|Resolved|post-pilot; reports; pdf|Reportlab-based one-page landscape A4 PDF generator (app/services/weekly_report_renderer.py). New endpoints: GET /api/reports/weekly?projectId=... and POST /api/reports/weekly/send-now. Notification scheduler tick every Friday at 11:30 UTC (5:00 PM IST) iterates all active projects and emails the PDF to each project's assigned stakeholders (falls back to all org stakeholders). SMTP via existing Google App password. Download PDF button on Stakeholder -> Export page."
  "Weekly PDF polish - semicircle gauge, dark text, milestone wrapping, real predictability|Resolved|post-pilot; reports; pdf|Second-pass fixes after pilot review: (1) replaced meaningless PROJECT # code with a semicircle completion gauge matching the reference PDF; (2) darkened entire text palette (slate-900/800/700/600) for legibility when printed or shared; (3) fixed Progress + Predictability cards that were always empty - root cause was an if phases: gate blocking velocityTrend load from team-health engine; added DB fallback that averages completion ratios across last 5 sprints; (4) milestone names now wrap to 2 lines so AI Sprint Planning & Resource Optimization is no longer truncated to AI Sprint Planning & Resource Opti."
  "Data integrity - repair 56 orphan iteration links on Plan2Sprint project|Resolved|post-pilot; data-fix|Diagnosed and fixed 56 work_items linked to a deleted iteration_id (f29081c7792641eaa5a99336f - Iteration 3 of a stale project). Built a one-shot admin endpoint /_admin/repair-iteration-links that matches by iteration name and re-links orphan rows. Verified on Plan2Sprint project (id 2328c3fed9c142b1b9458a4b1), then removed the debug endpoint."
  "UI polish - drawer theme-aware bg, navbar shadow, dashboard gradients|Resolved|post-pilot; ui|Collection of small quality fixes: (1) Notes drawer uses --bg-surface so it is opaque in both dark and light mode; (2) drawer height fixed with explicit 100vh (Framer Motion transform was collapsing the flex column); (3) top navbar shadow changed from radial 0 0 80px rgba(0,0,0,0.7) to directional -12px 0 32px to stop shadow bleed onto the 'Product Owner Dashboard' title; (4) removed full Velocity section from Developer dashboard; (5) Product Owner velocity reformatted as compact per-dev percentage bars instead of a separate sidebar; (6) added gradient accents + section summaries with conclusion sentences across dashboards."
  "Fix automated digest scheduling when ACA scales to zero|New|planned; infra; scheduling|Problem: Plan2Sprint API container scales to 0 replicas when idle. The in-process asyncio notification_scheduler can only fire while the container is awake, so morning/evening digests and the Friday weekly report tick are silently skipped. Impact observed during pilot - stakeholders reported missing Slack digests. Options: (a) minReplicas=1 on the Container App (simplest, ~\$5/mo); (b) external cron (GitHub Actions / Azure Logic App) that hits a /api/tick endpoint every 10 min to wake the container; (c) move scheduling to Azure Functions Timer trigger. Pick one, implement, verify Friday 5 PM IST weekly report + 9 AM / 5 PM IST digests fire reliably for 2 consecutive weeks."
  "Weekly PDF - graceful empty-project edge cases|New|planned; reports; pdf|When a project has no iterations, no work items, or no team health data, render a clean PDF instead of a half-empty one or a 500. Acceptance criteria: (1) project with 0 sprints -> timeline bar shows a single Planning stage; (2) project with 0 work items -> progress card shows 0% and narrative 'Project is in setup - no work items imported yet'; (3) team_health_engine returns None -> team health card shows em-dash with label 'Not enough data yet'; (4) zero upcoming milestones -> hide the milestones strip and expand cards row to fill vertical space. Test on a brand-new imported project before closing."
)

echo "Creating ${#ITEMS[@]} work items in $ORG/$PROJECT..."
CREATED_IDS=()

for row in "${ITEMS[@]}"; do
  IFS='|' read -r TITLE STATE TAGS DESC <<< "$row"

  echo ""
  echo "Creating: $TITLE"

  ID=$(az boards work-item create \
    --organization "$ORG" \
    --project "$PROJECT" \
    --type "User Story" \
    --title "$TITLE" \
    --area "$AREA" \
    --output tsv --query "id" 2>/dev/null | tr -d '\r' | tr -d '[:space:]')

  if [[ -z "$ID" ]]; then
    echo "  ERROR: create failed — skipping"
    continue
  fi
  echo "  id=$ID, applying description + state + tags..."

  az boards work-item update --id "$ID" \
    --organization "$ORG" \
    --description "$DESC" \
    --state "$STATE" \
    --fields "System.Tags=$TAGS" \
    --output none 2>/dev/null || echo "  WARN: update had issues"

  CREATED_IDS+=("$ID")
done

echo ""
echo "Done. Created IDs: ${CREATED_IDS[*]}"

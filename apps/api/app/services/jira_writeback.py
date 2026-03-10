"""
Jira Write-back Service — batch write-back of approved sprint plan to Jira Cloud.

After a sprint plan is approved:
  1. Load the approved plan and all assignments from DB
  2. Validate pre-conditions (plan is APPROVED, Jira connected, token valid)
  3. For each assignment, PUT the Jira issue with:
     - assignee (account ID)
     - story_points (customfield_10016)
  4. Move issues to the correct sprint via Agile API (sprint_id)
  5. Add a comment to each issue with assignment rationale
  6. Log each write-back in the audit log
  7. Update the plan's synced_at timestamp and status
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.sprint_plan import SprintPlan, PlanAssignment
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.iteration import Iteration
from ..models.audit_log import AuditLogEntry
from ..models.tool_connection import ToolConnection
from ..models.imported_project import ImportedProject
from ..services.encryption import decrypt_token

import httpx

logger = logging.getLogger(__name__)

# Write-back allowlist (must match the frozen set in jira.py / writeback.ts)
JIRA_WRITEBACK_ALLOWLIST = frozenset([
    "assignee",
    "sprint_id",
    "story_points",
    "status",
])

ATLASSIAN_API_BASE = "https://api.atlassian.com"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"


# ---------------------------------------------------------------------------
# Jira helpers
# ---------------------------------------------------------------------------

async def _get_jira_connection(db: AsyncSession, org_id: str) -> ToolConnection | None:
    result = await db.execute(
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .where(ToolConnection.source_tool == "JIRA")
        .order_by(ToolConnection.created_at.desc())
    )
    return result.scalar_one_or_none()


def _get_auth_info(conn: ToolConnection) -> tuple[str, str | None]:
    """Return (base_url, auth_header_override) for the Jira connection."""
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "api_token":
        site_url = config.get("site_url", "")
        email = config.get("email", "")
        api_token = decrypt_token(conn.access_token)
        auth_str = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        return site_url, f"Basic {auth_str}"
    else:
        cloud_id = config.get("cloud_id", "")
        return f"{ATLASSIAN_API_BASE}/ex/jira/{cloud_id}", None


async def _get_valid_token(db: AsyncSession, conn: ToolConnection) -> str:
    """Get a valid access token, refreshing if needed (Atlassian tokens expire in 1h)."""
    from ..config import settings

    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "api_token":
        return decrypt_token(conn.access_token)

    refresh_token = config.get("refresh_token")
    access_token = decrypt_token(conn.access_token)

    token_age = None
    if config.get("token_updated_at"):
        try:
            updated = datetime.fromisoformat(config["token_updated_at"])
            token_age = (datetime.now(timezone.utc) - updated).total_seconds()
        except (ValueError, TypeError):
            pass

    if token_age and token_age > 3000 and refresh_token:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    ATLASSIAN_TOKEN_URL,
                    json={
                        "grant_type": "refresh_token",
                        "client_id": settings.jira_client_id,
                        "client_secret": settings.jira_client_secret,
                        "refresh_token": refresh_token,
                    },
                )
                if res.status_code == 200:
                    from ..services.encryption import encrypt_token
                    tokens = res.json()
                    new_access = tokens["access_token"]
                    new_refresh = tokens.get("refresh_token", refresh_token)

                    conn.access_token = encrypt_token(new_access)
                    config["refresh_token"] = new_refresh
                    config["token_updated_at"] = datetime.now(timezone.utc).isoformat()
                    conn.config = config
                    await db.flush()
                    return new_access
        except Exception as e:
            logger.warning(f"Jira token refresh failed: {e}")

    return access_token


async def _jira_put(
    url: str,
    access_token: str,
    json_body: dict,
    auth_header: str | None = None,
) -> dict:
    """PUT a Jira issue update."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.put(url, headers=headers, json=json_body)
        if res.is_error:
            logger.error(f"Jira PUT {url} failed: {res.status_code} {res.text[:300]}")
            return {"error": f"Jira API error: {res.status_code}", "status_code": res.status_code}
        if res.status_code == 204:
            return {"ok": True}
        return res.json()


async def _jira_post(
    url: str,
    access_token: str,
    json_body: dict,
    auth_header: str | None = None,
) -> dict:
    """POST to Jira API (comments, sprint moves)."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, headers=headers, json=json_body)
        if res.is_error:
            logger.error(f"Jira POST {url} failed: {res.status_code} {res.text[:300]}")
            return {"error": f"Jira API error: {res.status_code}", "status_code": res.status_code}
        if res.status_code == 204:
            return {"ok": True}
        return res.json()


# ---------------------------------------------------------------------------
# MAIN: execute_batch_writeback
# ---------------------------------------------------------------------------

async def execute_batch_writeback(
    db: AsyncSession,
    plan_id: str,
    org_id: str,
    approver_id: str = "system",
) -> dict:
    """
    Execute batch write-back of approved plan assignments to Jira.

    Returns: { synced: int, pending: int, failed: int, errors: [...] }
    """

    # 1. Load the plan
    plan_result = await db.execute(
        select(SprintPlan).where(SprintPlan.id == plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        return {"error": "Plan not found", "synced": 0, "pending": 0, "failed": 0}

    if plan.status not in ("APPROVED", "SYNCING"):
        return {"error": f"Plan status is {plan.status}, expected APPROVED", "synced": 0, "pending": 0, "failed": 0}

    # 2. Get Jira connection
    conn = await _get_jira_connection(db, org_id)
    if not conn:
        return {"error": "Jira not connected", "synced": 0, "pending": 0, "failed": 0}

    base_url, auth_header = _get_auth_info(conn)
    if not base_url:
        return {"error": "No Jira base URL", "synced": 0, "pending": 0, "failed": 0}

    access_token = await _get_valid_token(db, conn)

    # 3. Load iteration for sprint ID
    iter_result = await db.execute(
        select(Iteration).where(Iteration.id == plan.iteration_id)
    )
    iteration = iter_result.scalar_one_or_none()

    # The iteration's external_id maps to the Jira sprint ID
    jira_sprint_id = iteration.external_id if iteration else None

    # 4. Load assignments with work items and team members
    assign_result = await db.execute(
        select(PlanAssignment).where(PlanAssignment.sprint_plan_id == plan_id)
    )
    assignments = list(assign_result.scalars().all())

    if not assignments:
        plan.status = "SYNCED"
        plan.synced_at = datetime.now(timezone.utc)
        await db.commit()
        return {"synced": 0, "pending": 0, "failed": 0, "errors": []}

    # Load work items and team members
    wi_ids = [a.work_item_id for a in assignments]
    tm_ids = list(set(a.team_member_id for a in assignments))

    wi_result = await db.execute(
        select(WorkItem).where(WorkItem.id.in_(wi_ids))
    )
    work_items = {wi.id: wi for wi in wi_result.scalars().all()}

    tm_result = await db.execute(
        select(TeamMember).where(TeamMember.id.in_(tm_ids))
    )
    team_members = {tm.id: tm for tm in tm_result.scalars().all()}

    # Get approver display name
    approver_name = approver_id

    # 5. Update plan status to SYNCING
    plan.status = "SYNCING"
    await db.flush()

    # 6. Execute write-back for each assignment
    synced = 0
    failed = 0
    errors: list[str] = []

    # Collect issue keys that need to be moved to the sprint (batch sprint move)
    sprint_move_issues: list[str] = []

    for assignment in assignments:
        wi = work_items.get(assignment.work_item_id)
        tm = team_members.get(assignment.team_member_id)

        if not wi or not tm:
            errors.append(f"Missing data for assignment {assignment.id}")
            failed += 1
            continue

        external_id = wi.external_id
        if not external_id:
            errors.append(f"No external_id for work item {wi.id}")
            failed += 1
            continue

        # Build Jira field update payload
        # Map Plan2Sprint fields → Jira API field names
        jira_fields: dict = {}

        # Assignee: use the team member's external_id (Jira accountId)
        # Fall back to email-based lookup if no external_id
        if tm.external_id:
            jira_fields["assignee"] = {"accountId": tm.external_id}
        elif tm.email:
            jira_fields["assignee"] = {"accountId": tm.email}

        # Story points (Jira custom field — varies by instance, 10016 is common)
        jira_fields["customfield_10016"] = assignment.story_points

        # Execute the PUT to update the issue
        try:
            result = await _jira_put(
                f"{base_url}/rest/api/3/issue/{external_id}",
                access_token,
                {"fields": jira_fields},
                auth_header,
            )

            if "error" in result:
                errors.append(f"Jira PUT failed for {external_id}: {result['error']}")
                failed += 1

                # Audit log — failed
                _add_audit_entry(
                    db, org_id, approver_id, "writeback_failed", "work_item",
                    wi.id, success=False,
                    metadata={
                        "tool": "jira",
                        "externalId": external_id,
                        "itemTitle": wi.title,
                        "error": result["error"],
                    },
                )
                continue

            # Track for sprint move
            if jira_sprint_id:
                sprint_move_issues.append(external_id)

            # Add a comment with assignment rationale
            conf_pct = round(assignment.confidence_score * 100) if assignment.confidence_score <= 1.0 else round(assignment.confidence_score)
            comment_body = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Plan2Sprint Sprint Assignment", "marks": [{"type": "strong"}]},
                            ],
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"Assigned to: {tm.display_name}\n"},
                                {"type": "text", "text": f"Story Points: {assignment.story_points:.0f}\n"},
                                {"type": "text", "text": f"Rationale: {assignment.rationale}\n"},
                                {"type": "text", "text": f"Confidence: {conf_pct}%\n"},
                                {"type": "text", "text": f"Approved by: {approver_name} on {plan.approved_at.strftime('%Y-%m-%d %H:%M') if plan.approved_at else 'N/A'}"},
                            ],
                        },
                    ],
                },
            }

            try:
                await _jira_post(
                    f"{base_url}/rest/api/3/issue/{external_id}/comment",
                    access_token,
                    comment_body,
                    auth_header,
                )
            except Exception as ce:
                logger.warning(f"Failed to add comment to {external_id}: {ce}")
                # Don't fail the whole write-back for a comment error

            synced += 1

            # Audit log — success
            _add_audit_entry(
                db, org_id, approver_id, "writeback", "work_item",
                wi.id, success=True,
                metadata={
                    "tool": "jira",
                    "externalId": external_id,
                    "itemTitle": wi.title,
                    "changes": [
                        {"field": "assignee", "from": None, "to": tm.external_id or tm.email},
                        {"field": "story_points", "from": wi.story_points, "to": assignment.story_points},
                        {"field": "sprint_id", "from": None, "to": jira_sprint_id},
                    ],
                    "undoable": True,
                },
            )

        except Exception as e:
            logger.error(f"Write-back error for {external_id}: {e}")
            errors.append(f"Exception for {external_id}: {str(e)[:100]}")
            failed += 1

            _add_audit_entry(
                db, org_id, approver_id, "writeback_failed", "work_item",
                wi.id, success=False,
                metadata={
                    "tool": "jira",
                    "externalId": external_id,
                    "itemTitle": wi.title,
                    "error": str(e)[:200],
                },
            )

    # 7. Batch sprint move via Agile API (more efficient than per-issue)
    if jira_sprint_id and sprint_move_issues:
        try:
            # Jira Agile API: POST /rest/agile/1.0/sprint/{sprintId}/issue
            config = conn.config or {}
            cloud_id = config.get("cloud_id", "")
            agile_base = f"{ATLASSIAN_API_BASE}/ex/jira/{cloud_id}" if cloud_id else base_url

            move_result = await _jira_post(
                f"{agile_base}/rest/agile/1.0/sprint/{jira_sprint_id}/issue",
                access_token,
                {"issues": sprint_move_issues},
                auth_header,
            )

            if "error" in move_result:
                logger.warning(f"Sprint move failed: {move_result['error']}")
                errors.append(f"Sprint move failed for {len(sprint_move_issues)} issues: {move_result['error']}")
            else:
                logger.info(f"Moved {len(sprint_move_issues)} issues to sprint {jira_sprint_id}")

        except Exception as e:
            logger.warning(f"Sprint move error: {e}")
            errors.append(f"Sprint move exception: {str(e)[:100]}")

    # 8. Update plan status
    if failed == 0:
        plan.status = "SYNCED"
    else:
        plan.status = "SYNCED_PARTIAL"

    plan.synced_at = datetime.now(timezone.utc)
    plan.undo_available_until = datetime.now(timezone.utc) + timedelta(minutes=60)
    await db.commit()

    logger.info(
        f"Jira write-back complete for plan {plan_id}: "
        f"{synced} synced, {failed} failed, {len(errors)} errors"
    )

    return {
        "synced": synced,
        "pending": 0,
        "failed": failed,
        "errors": errors,
    }


def _add_audit_entry(
    db: AsyncSession,
    org_id: str,
    actor_id: str,
    event_type: str,
    resource_type: str,
    resource_id: str,
    success: bool = True,
    metadata: dict | None = None,
):
    """Add an audit log entry (synchronous, flushed in batch)."""
    entry = AuditLogEntry(
        id=generate_cuid(),
        organization_id=org_id,
        actor_id=actor_id,
        actor_role="product_owner",
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        success=success,
        metadata_=metadata,
    )
    db.add(entry)


# ---------------------------------------------------------------------------
# Jira helper: GET request (for transition discovery)
# ---------------------------------------------------------------------------

async def _jira_get(
    url: str,
    access_token: str,
    auth_header: str | None = None,
) -> dict:
    """GET from Jira API."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.get(url, headers=headers)
        if res.is_error:
            logger.error(f"Jira GET {url} failed: {res.status_code} {res.text[:300]}")
            return {"error": f"Jira API error: {res.status_code}", "status_code": res.status_code}
        return res.json()


async def _find_transition(
    base_url: str,
    access_token: str,
    issue_key: str,
    target_name: str,
    fallback_category: str,
    auth_header: str | None = None,
) -> dict | None:
    """
    Discover the right transition ID for an issue to reach the target status.

    1. GET /rest/api/3/issue/{key}/transitions
    2. Match by exact target status name (case-insensitive)
    3. Fallback: match by statusCategory.key
    """
    result = await _jira_get(
        f"{base_url}/rest/api/3/issue/{issue_key}/transitions",
        access_token,
        auth_header,
    )

    if "error" in result:
        return None

    transitions = result.get("transitions", [])
    target_lower = target_name.lower().strip()

    # Priority 1: exact name match
    for t in transitions:
        to_status = t.get("to", {})
        if to_status.get("name", "").lower().strip() == target_lower:
            return {"id": t["id"], "name": t.get("name", ""), "toStatus": to_status.get("name", "")}

    # Priority 2: category match
    for t in transitions:
        to_status = t.get("to", {})
        cat = to_status.get("statusCategory", {}).get("key", "")
        if cat.lower() == fallback_category.lower():
            return {"id": t["id"], "name": t.get("name", ""), "toStatus": to_status.get("name", "")}

    return None


# ---------------------------------------------------------------------------
# Board Status Write-Back — write board column changes to Jira via transitions
# ---------------------------------------------------------------------------

async def writeback_board_statuses(
    db: AsyncSession,
    org_id: str,
    changes: list[dict],
    approver_id: str = "system",
) -> dict:
    """
    Write back board status changes from Plan2Sprint to Jira.

    Each change dict: {
        "workItemId": "internal-id",
        "externalId": "PROJ-123",
        "fromStatus": "TODO",
        "toStatus": "IN_PROGRESS",
        "title": "Item title",
    }

    For Jira, status changes require transitions:
    1. GET available transitions for the issue
    2. Find transition matching the target status
    3. POST the transition to execute it

    Returns: { synced: int, failed: int, errors: [...] }
    """
    from ..adapters.status_maps import reverse_map_jira_status

    # 1. Get Jira connection
    conn = await _get_jira_connection(db, org_id)
    if not conn:
        return {"error": "Jira not connected", "synced": 0, "failed": 0}

    base_url, auth_header = _get_auth_info(conn)
    if not base_url:
        return {"error": "No Jira base URL", "synced": 0, "failed": 0}

    access_token = await _get_valid_token(db, conn)

    synced = 0
    failed = 0
    errors: list[str] = []
    results: list[dict] = []

    for change in changes:
        external_id = change.get("externalId", "")
        to_status = change.get("toStatus", "")
        from_status = change.get("fromStatus", "")
        title = change.get("title", external_id)
        work_item_id = change.get("workItemId", "")

        if not external_id or not to_status:
            errors.append(f"Missing externalId or toStatus for change")
            failed += 1
            continue

        # Map unified status to Jira target (name + fallback category)
        target_name, fallback_category = reverse_map_jira_status(to_status)

        try:
            # Discover the right transition
            transition = await _find_transition(
                base_url, access_token, external_id,
                target_name, fallback_category, auth_header,
            )

            if not transition:
                msg = f"No transition found for {external_id} to reach '{target_name}'"
                errors.append(msg)
                failed += 1
                _add_audit_entry(
                    db, org_id, approver_id, "board_writeback_failed",
                    "work_item", work_item_id, success=False,
                    metadata={
                        "tool": "jira",
                        "externalId": external_id,
                        "itemTitle": title,
                        "targetStatus": target_name,
                        "error": msg,
                    },
                )
                results.append({"externalId": external_id, "ok": False, "error": msg})
                continue

            # Execute the transition
            transition_result = await _jira_post(
                f"{base_url}/rest/api/3/issue/{external_id}/transitions",
                access_token,
                {"transition": {"id": transition["id"]}},
                auth_header,
            )

            if "error" in transition_result:
                errors.append(f"Jira transition failed for {external_id}: {transition_result['error']}")
                failed += 1
                _add_audit_entry(
                    db, org_id, approver_id, "board_writeback_failed",
                    "work_item", work_item_id, success=False,
                    metadata={
                        "tool": "jira",
                        "externalId": external_id,
                        "itemTitle": title,
                        "error": transition_result["error"],
                    },
                )
                results.append({"externalId": external_id, "ok": False, "error": transition_result["error"]})
                continue

            # Add a comment
            comment_body = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Plan2Sprint Board Update", "marks": [{"type": "strong"}]},
                            ],
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"Status changed: {from_status} -> {to_status}\n"},
                                {"type": "text", "text": f"Jira transition: {transition['name']} -> {transition['toStatus']}\n"},
                                {"type": "text", "text": "Updated via Plan2Sprint sprint board"},
                            ],
                        },
                    ],
                },
            }

            try:
                await _jira_post(
                    f"{base_url}/rest/api/3/issue/{external_id}/comment",
                    access_token,
                    comment_body,
                    auth_header,
                )
            except Exception as ce:
                logger.warning(f"Failed to add board comment to {external_id}: {ce}")

            synced += 1
            results.append({
                "externalId": external_id,
                "ok": True,
                "transitionUsed": transition["name"],
                "jiraStatus": transition["toStatus"],
            })

            _add_audit_entry(
                db, org_id, approver_id, "board_writeback",
                "work_item", work_item_id, success=True,
                metadata={
                    "tool": "jira",
                    "externalId": external_id,
                    "itemTitle": title,
                    "fromStatus": from_status,
                    "toStatus": to_status,
                    "transitionUsed": transition["name"],
                    "jiraStatus": transition["toStatus"],
                },
            )

        except Exception as e:
            logger.error(f"Jira board writeback error for {external_id}: {e}")
            errors.append(f"Exception for {external_id}: {str(e)[:100]}")
            failed += 1
            _add_audit_entry(
                db, org_id, approver_id, "board_writeback_failed",
                "work_item", work_item_id, success=False,
                metadata={
                    "tool": "jira",
                    "externalId": external_id,
                    "error": str(e)[:200],
                },
            )

    await db.commit()

    logger.info(f"Jira board writeback: {synced} synced, {failed} failed")
    return {"synced": synced, "failed": failed, "errors": errors, "results": results}

"""
ADO Write-back Service — batch write-back of approved sprint plan to Azure DevOps.

After a sprint plan is approved:
  1. Load the approved plan and all assignments from DB
  2. Validate pre-conditions (plan is APPROVED, ADO connected, token valid)
  3. For each assignment, add a rich AI recommendation comment (System.History)
  4. Log each write-back in the audit log
  5. Update the plan's synced_at timestamp and status

NOTE: No fields are modified on the ADO work item (no AssignedTo, IterationPath, or StoryPoints changes).
      The comment serves as an AI recommendation that the team can act on manually.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# ADO helpers
# ---------------------------------------------------------------------------

async def _get_ado_connection(db: AsyncSession, org_id: str) -> ToolConnection | None:
    result = await db.execute(
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .where(ToolConnection.source_tool == "ADO")
        .order_by(ToolConnection.created_at.desc())
    )
    return result.scalar_one_or_none()


def _get_auth_info(conn: ToolConnection) -> tuple[str, str | None]:
    import base64
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")
    org_url = config.get("org_url", "")

    if auth_method == "pat":
        pat = decrypt_token(conn.access_token)
        auth_str = base64.b64encode(f":{pat}".encode()).decode()
        return org_url, f"Basic {auth_str}"
    return org_url, None


async def _get_valid_token(db: AsyncSession, conn: ToolConnection) -> str:
    from ..config import settings

    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "pat":
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
        ADO_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"
        ADO_SCOPE = f"{ADO_RESOURCE_ID}/.default offline_access"
        tenant_id = settings.ado_tenant_id or "common"
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    token_url,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": settings.ado_client_id,
                        "client_secret": settings.ado_client_secret,
                        "refresh_token": refresh_token,
                        "scope": ADO_SCOPE,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
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
            logger.warning(f"Token refresh failed: {e}")

    return access_token


async def _ado_patch(
    url: str,
    access_token: str,
    patch_document: list[dict],
    auth_header: str | None = None,
) -> dict:
    """PATCH an ADO work item."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json-patch+json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.patch(
            url,
            headers=headers,
            content=json.dumps(patch_document),
        )
        if res.is_error:
            logger.error(f"ADO PATCH {url} failed: {res.status_code} {res.text[:300]}")
            return {"error": f"ADO API error: {res.status_code}", "status_code": res.status_code}
        if res.status_code == 204:
            return {"ok": True}
        return res.json()


# ---------------------------------------------------------------------------
# Comment builder
# ---------------------------------------------------------------------------

def _build_recommendation_html(
    assignment: PlanAssignment,
    plan: SprintPlan,
) -> str:
    """Build a rich HTML comment for the AI recommendation."""
    conf_pct = (
        round(assignment.confidence_score * 100)
        if assignment.confidence_score <= 1.0
        else round(assignment.confidence_score)
    )
    risk_flags_str = ", ".join(assignment.risk_flags) if assignment.risk_flags else "None"
    rationale_text = assignment.rationale or "No rationale provided."
    model_used = plan.ai_model_used if hasattr(plan, "ai_model_used") and plan.ai_model_used else "auto"
    approved_date = (
        plan.approved_at.strftime("%Y-%m-%d %H:%M UTC")
        if plan.approved_at
        else "N/A"
    )

    return (
        '<div style="border:1px solid #ddd;border-radius:6px;padding:16px;margin:8px 0;">'
        '<h3 style="margin:0 0 12px 0;color:#0078d4;">Plan2Sprint AI Recommendation</h3>'
        '<table style="border-collapse:collapse;width:100%;">'
        f'<tr><td style="padding:4px 8px;font-weight:600;">Recommended Sprint</td>'
        f'<td style="padding:4px 8px;">Sprint {assignment.sprint_number}</td></tr>'
        f'<tr><td style="padding:4px 8px;font-weight:600;">AI-Estimated Story Points</td>'
        f'<td style="padding:4px 8px;">{assignment.story_points:.0f}</td></tr>'
        f'<tr><td style="padding:4px 8px;font-weight:600;">Confidence</td>'
        f'<td style="padding:4px 8px;">{conf_pct}%</td></tr>'
        f'<tr><td style="padding:4px 8px;font-weight:600;">Risk Flags</td>'
        f'<td style="padding:4px 8px;">{risk_flags_str}</td></tr>'
        '</table>'
        f'<p style="margin:12px 0 4px;"><b>Rationale:</b> {rationale_text}</p>'
        f'<p style="color:#888;font-size:12px;margin:8px 0 0;">'
        f'Generated by Plan2Sprint AI ({model_used}) | Approved {approved_date}'
        '</p></div>'
    )


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
    Execute batch write-back of approved plan assignments to ADO.

    Posts an AI recommendation comment (System.History) to each work item.
    No fields are modified — comments are non-destructive.

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

    # 2. Get ADO connection
    conn = await _get_ado_connection(db, org_id)
    if not conn:
        return {"error": "ADO not connected", "synced": 0, "pending": 0, "failed": 0}

    org_url, auth_header = _get_auth_info(conn)
    if not org_url:
        return {"error": "No ADO org URL", "synced": 0, "pending": 0, "failed": 0}

    access_token = await _get_valid_token(db, conn)

    # 3. Load assignments with work items
    assign_result = await db.execute(
        select(PlanAssignment).where(PlanAssignment.sprint_plan_id == plan_id)
    )
    assignments = list(assign_result.scalars().all())

    if not assignments:
        plan.status = "SYNCED"
        plan.synced_at = datetime.now(timezone.utc)
        await db.commit()
        return {"synced": 0, "pending": 0, "failed": 0, "errors": []}

    # Load work items
    wi_ids = [a.work_item_id for a in assignments]
    wi_result = await db.execute(
        select(WorkItem).where(WorkItem.id.in_(wi_ids))
    )
    work_items = {wi.id: wi for wi in wi_result.scalars().all()}

    # 4. Update plan status to SYNCING
    plan.status = "SYNCING"
    await db.flush()

    # 5. Post AI recommendation comment for each assignment
    synced = 0
    failed = 0
    errors: list[str] = []

    for assignment in assignments:
        wi = work_items.get(assignment.work_item_id)

        if not wi:
            errors.append(f"Missing work item for assignment {assignment.id}")
            failed += 1
            continue

        external_id = wi.external_id
        if not external_id:
            errors.append(f"No external_id for work item {wi.id}")
            failed += 1
            continue

        # Build rich HTML comment
        comment_html = _build_recommendation_html(assignment, plan)

        comment_patch = [
            {
                "op": "add",
                "path": "/fields/System.History",
                "value": comment_html,
            }
        ]

        try:
            result = await _ado_patch(
                f"{org_url}/_apis/wit/workitems/{external_id}?api-version=7.1",
                access_token,
                comment_patch,
                auth_header,
            )

            if "error" in result:
                errors.append(f"Comment PATCH failed for {external_id}: {result['error']}")
                failed += 1

                _add_audit_entry(
                    db, org_id, approver_id, "comment_failed", "work_item",
                    wi.id, success=False,
                    metadata={
                        "tool": "ado",
                        "externalId": external_id,
                        "itemTitle": wi.title,
                        "error": result["error"],
                    },
                )
                continue

            synced += 1

            # Audit log — success
            conf_pct = (
                round(assignment.confidence_score * 100)
                if assignment.confidence_score <= 1.0
                else round(assignment.confidence_score)
            )
            _add_audit_entry(
                db, org_id, approver_id, "comment_posted", "work_item",
                wi.id, success=True,
                metadata={
                    "tool": "ado",
                    "externalId": external_id,
                    "itemTitle": wi.title,
                    "action": "comment_posted",
                    "commentSummary": {
                        "recommendedSprint": assignment.sprint_number,
                        "aiEstimatedSP": assignment.story_points,
                        "confidence": conf_pct,
                        "riskFlags": list(assignment.risk_flags) if assignment.risk_flags else [],
                    },
                    "undoable": False,
                },
            )

        except Exception as e:
            logger.error(f"Comment error for {external_id}: {e}")
            errors.append(f"Exception for {external_id}: {str(e)[:100]}")
            failed += 1

            _add_audit_entry(
                db, org_id, approver_id, "comment_failed", "work_item",
                wi.id, success=False,
                metadata={
                    "tool": "ado",
                    "externalId": external_id,
                    "itemTitle": wi.title,
                    "error": str(e)[:200],
                },
            )

    # 6. Update plan status
    if failed == 0:
        plan.status = "SYNCED"
    else:
        plan.status = "SYNCED_PARTIAL"

    plan.synced_at = datetime.now(timezone.utc)
    plan.undo_available_until = None  # No undo for comment-based sync
    await db.commit()

    logger.info(
        f"ADO comment sync complete for plan {plan_id}: "
        f"{synced} commented, {failed} failed, {len(errors)} errors"
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
# Board Status Write-Back — write board column changes to ADO
# ---------------------------------------------------------------------------

async def writeback_board_statuses(
    db: AsyncSession,
    org_id: str,
    changes: list[dict],
    approver_id: str = "system",
) -> dict:
    """
    Write back board status changes from Plan2Sprint to ADO.

    Each change dict: {
        "workItemId": "internal-id",
        "externalId": "12345",
        "fromStatus": "TODO",
        "toStatus": "IN_PROGRESS",
        "title": "Item title",
    }

    Returns: { synced: int, failed: int, errors: [...] }
    """
    from ..adapters.status_maps import reverse_map_ado_status

    # 1. Get ADO connection
    conn = await _get_ado_connection(db, org_id)
    if not conn:
        return {"error": "ADO not connected", "synced": 0, "failed": 0}

    org_url, auth_header = _get_auth_info(conn)
    if not org_url:
        return {"error": "No ADO org URL", "synced": 0, "failed": 0}

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

        # Map unified status to ADO System.State
        ado_state = reverse_map_ado_status(to_status)

        # Build PATCH document
        patch_document = [
            {
                "op": "replace",
                "path": "/fields/System.State",
                "value": ado_state,
            },
        ]

        try:
            result = await _ado_patch(
                f"{org_url}/_apis/wit/workitems/{external_id}?api-version=7.1",
                access_token,
                patch_document,
                auth_header,
            )

            if "error" in result:
                errors.append(f"ADO PATCH failed for {external_id}: {result['error']}")
                failed += 1
                _add_audit_entry(
                    db, org_id, approver_id, "board_writeback_failed",
                    "work_item", work_item_id, success=False,
                    metadata={
                        "tool": "ado",
                        "externalId": external_id,
                        "itemTitle": title,
                        "fromStatus": from_status,
                        "toStatus": to_status,
                        "adoState": ado_state,
                        "error": result["error"],
                    },
                )
                results.append({"externalId": external_id, "ok": False, "error": result["error"]})
                continue

            # Add a discussion comment
            comment_html = (
                f"<b>Plan2Sprint Board Update</b><br>"
                f"Status changed: {from_status} -> {to_status}<br>"
                f"ADO State set to: {ado_state}<br>"
                f"Updated via Plan2Sprint sprint board"
            )
            comment_patch = [
                {"op": "add", "path": "/fields/System.History", "value": comment_html}
            ]

            try:
                await _ado_patch(
                    f"{org_url}/_apis/wit/workitems/{external_id}?api-version=7.1",
                    access_token,
                    comment_patch,
                    auth_header,
                )
            except Exception as ce:
                logger.warning(f"Failed to add board comment to {external_id}: {ce}")

            synced += 1
            results.append({"externalId": external_id, "ok": True, "adoState": ado_state})

            _add_audit_entry(
                db, org_id, approver_id, "board_writeback",
                "work_item", work_item_id, success=True,
                metadata={
                    "tool": "ado",
                    "externalId": external_id,
                    "itemTitle": title,
                    "fromStatus": from_status,
                    "toStatus": to_status,
                    "adoState": ado_state,
                },
            )

        except Exception as e:
            logger.error(f"Board writeback error for {external_id}: {e}")
            errors.append(f"Exception for {external_id}: {str(e)[:100]}")
            failed += 1
            _add_audit_entry(
                db, org_id, approver_id, "board_writeback_failed",
                "work_item", work_item_id, success=False,
                metadata={
                    "tool": "ado",
                    "externalId": external_id,
                    "error": str(e)[:200],
                },
            )

    await db.commit()

    logger.info(f"ADO board writeback: {synced} synced, {failed} failed")
    return {"synced": synced, "failed": failed, "errors": errors, "results": results}

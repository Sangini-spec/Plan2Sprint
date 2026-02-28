"""
ADO Write-back Service — batch write-back of approved sprint plan to Azure DevOps.

After a sprint plan is approved:
  1. Load the approved plan and all assignments from DB
  2. Validate pre-conditions (plan is APPROVED, ADO connected, token valid)
  3. For each assignment, PATCH the ADO work item with:
     - System.AssignedTo (assignee email)
     - System.IterationPath (sprint iteration path)
     - Microsoft.VSTS.Scheduling.StoryPoints (story points)
  4. Add a Discussion comment (System.History) to each work item
  5. Log each write-back in the audit log
  6. Update the plan's synced_at timestamp and status
"""

from __future__ import annotations

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

# Write-back allowlist (must match the frozen set in ado.py)
ADO_WRITEBACK_ALLOWLIST = frozenset([
    "System.AssignedTo",
    "System.IterationPath",
    "Microsoft.VSTS.Scheduling.StoryPoints",
])


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

    # 3. Load iteration for path
    iter_result = await db.execute(
        select(Iteration).where(Iteration.id == plan.iteration_id)
    )
    iteration = iter_result.scalar_one_or_none()

    # Try to find the iteration path from cached data
    iteration_path = ""
    if iteration:
        # ADO iteration path format: "ProjectName\\Sprint Name"
        # We need to find the project name
        if plan.project_id:
            proj_result = await db.execute(
                select(ImportedProject).where(ImportedProject.id == plan.project_id)
            )
            project = proj_result.scalar_one_or_none()
            if project:
                iteration_path = f"{project.name}\\{iteration.name}"
        if not iteration_path:
            iteration_path = iteration.name

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

        # Build PATCH document for the 3 allowed fields
        patch_document = [
            {
                "op": "replace",
                "path": "/fields/System.AssignedTo",
                "value": tm.email,
            },
            {
                "op": "replace",
                "path": "/fields/System.IterationPath",
                "value": iteration_path,
            },
            {
                "op": "replace",
                "path": "/fields/Microsoft.VSTS.Scheduling.StoryPoints",
                "value": assignment.story_points,
            },
        ]

        # Execute the PATCH
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

                # Audit log — failed
                _add_audit_entry(
                    db, org_id, approver_id, "writeback_failed", "work_item",
                    wi.id, success=False,
                    metadata={
                        "tool": "ado",
                        "externalId": external_id,
                        "itemTitle": wi.title,
                        "error": result["error"],
                    },
                )
                continue

            # Success — now add a Discussion comment
            conf_pct = round(assignment.confidence_score * 100) if assignment.confidence_score <= 1.0 else round(assignment.confidence_score)
            comment_html = (
                f"<b>Plan2Sprint Sprint Assignment</b><br>"
                f"Assigned to: {tm.display_name}<br>"
                f"Story Points: {assignment.story_points:.0f}<br>"
                f"Rationale: {assignment.rationale}<br>"
                f"Confidence: {conf_pct}%<br>"
                f"Approved by: {approver_name} on "
                f"{plan.approved_at.strftime('%Y-%m-%d %H:%M') if plan.approved_at else 'N/A'}"
            )

            comment_patch = [
                {
                    "op": "add",
                    "path": "/fields/System.History",
                    "value": comment_html,
                }
            ]

            try:
                await _ado_patch(
                    f"{org_url}/_apis/wit/workitems/{external_id}?api-version=7.1",
                    access_token,
                    comment_patch,
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
                    "tool": "ado",
                    "externalId": external_id,
                    "itemTitle": wi.title,
                    "changes": [
                        {"field": "System.AssignedTo", "from": None, "to": tm.email},
                        {"field": "System.IterationPath", "from": None, "to": iteration_path},
                        {"field": "Microsoft.VSTS.Scheduling.StoryPoints", "from": wi.story_points, "to": assignment.story_points},
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
                    "tool": "ado",
                    "externalId": external_id,
                    "itemTitle": wi.title,
                    "error": str(e)[:200],
                },
            )

    # 7. Update plan status
    if failed == 0:
        plan.status = "SYNCED"
    else:
        plan.status = "SYNCED_PARTIAL"

    plan.synced_at = datetime.now(timezone.utc)
    plan.undo_available_until = datetime.now(timezone.utc) + timedelta(minutes=60)
    await db.commit()

    logger.info(
        f"Write-back complete for plan {plan_id}: "
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

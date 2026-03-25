"""
Project Phases API — CRUD for customizable project lifecycle phases,
assignment rules, and board import.

GET    /api/projects/{projectId}/phases                    — List (auto-seeds defaults)
POST   /api/projects/{projectId}/phases                    — Create
PATCH  /api/projects/{projectId}/phases/{phaseId}          — Update
DELETE /api/projects/{projectId}/phases/{phaseId}           — Delete (reassign features)
PUT    /api/projects/{projectId}/phases/reorder             — Bulk reorder
GET    /api/projects/{projectId}/phases/{phaseId}/rules     — List rules
POST   /api/projects/{projectId}/phases/{phaseId}/rules     — Create rule
DELETE /api/projects/{projectId}/phases/rules/{ruleId}      — Delete rule
PATCH  /api/work-items/{itemId}/phase                       — Manual assignment
POST   /api/projects/{projectId}/phases/reassign            — Re-run all rules
POST   /api/projects/{projectId}/phases/import-from-board   — Import from ADO/Jira board
"""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.base import generate_cuid
from ..models.project_phase import ProjectPhase, PhaseAssignmentRule
from ..models.work_item import WorkItem

router = APIRouter()


# ── Pydantic schemas ──


class PhaseCreate(BaseModel):
    name: str
    color: str = "#6366f1"


class PhaseUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class PhaseReorder(BaseModel):
    phaseIds: list[str]


class PhaseDelete(BaseModel):
    targetPhaseId: Optional[str] = None


class RuleCreate(BaseModel):
    ruleType: str  # keyword, board_column, iteration_path
    pattern: str
    priority: int = 0


class ManualPhaseAssign(BaseModel):
    phaseId: Optional[str] = None


# ── Default phases definition ──

DEFAULT_PHASES = [
    {
        "name": "Discovery & Design",
        "slug": "discovery-design",
        "color": "#8b5cf6",
        "sort_order": 0,
        "rules": [
            {"rule_type": "keyword", "pattern": "design,discovery,ux,research,wireframe,prototype,onboarding,settings,landing", "priority": 0},
            {"rule_type": "board_column", "pattern": "new", "priority": 10},
        ],
    },
    {
        "name": "Core Development",
        "slug": "core-development",
        "color": "#3b82f6",
        "sort_order": 1,
        "rules": [
            {"rule_type": "keyword", "pattern": "development,implementation,build,core,authentication,dashboard,management,notification,standup,planning,workspace,role,project,sprint", "priority": 0},
            {"rule_type": "board_column", "pattern": "ready,in progress,active", "priority": 10},
        ],
    },
    {
        "name": "Integration & APIs",
        "slug": "integration-apis",
        "color": "#06b6d4",
        "sort_order": 2,
        "rules": [
            {"rule_type": "keyword", "pattern": "integration,api,webhook,oauth,connector,sync,slack,teams,gateway,write-back,approval", "priority": 0},
        ],
    },
    {
        "name": "Testing & QA",
        "slug": "testing-qa",
        "color": "#f59e0b",
        "sort_order": 3,
        "rules": [
            {"rule_type": "keyword", "pattern": "test,qa,automation,regression,e2e,health,burnout,retro,detection,signal", "priority": 0},
            {"rule_type": "board_column", "pattern": "testing,resolved", "priority": 10},
        ],
    },
    {
        "name": "UAT & Staging",
        "slug": "uat-staging",
        "color": "#f97316",
        "sort_order": 4,
        "rules": [
            {"rule_type": "keyword", "pattern": "uat,staging,acceptance,user acceptance,validation", "priority": 0},
            {"rule_type": "board_column", "pattern": "migrate,uat,staging", "priority": 10},
        ],
    },
    {
        "name": "Deployment & Launch",
        "slug": "deployment-launch",
        "color": "#22c55e",
        "sort_order": 5,
        "rules": [
            {"rule_type": "keyword", "pattern": "deploy,launch,migration,release,go-live", "priority": 0},
            {"rule_type": "board_column", "pattern": "closed,done", "priority": 10},
        ],
    },
]


def _slugify(name: str) -> str:
    """Convert phase name to URL-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:100]


# ── Phase resolution engine ──


def resolve_phase_for_feature(
    title: str,
    source_status: str | None,
    iteration_path: str | None,
    rules: list[dict],
    item_type: str | None = None,
) -> str | None:
    """
    Run assignment rules against a feature to determine its phase_id.

    For epic/feature-level items, keyword rules are tried first (features
    describe *what* they are — "Authentication", "Integration" etc.) then
    board_column as fallback.  For stories/tasks, board_column rules fire
    first (stories flow through board columns).
    """
    is_high_level = item_type in ("feature", "epic")

    # Build ordered rule list based on item type.
    # sort_order (phase position) is used as a tiebreaker for determinism.
    if is_high_level:
        # keyword first, then board_column, then iteration_path
        priority_order = {"keyword": 0, "iteration_path": 1, "board_column": 2}
        sorted_rules = sorted(
            rules,
            key=lambda r: (
                priority_order.get(r["rule_type"], 9),
                -r["priority"],
                r.get("sort_order", 99),
            ),
        )
    else:
        # Default: descending priority, then phase sort_order as tiebreaker
        sorted_rules = sorted(
            rules,
            key=lambda r: (-r["priority"], r.get("sort_order", 99)),
        )

    for rule in sorted_rules:
        rt = rule["rule_type"]
        patterns = [p.strip().lower() for p in rule["pattern"].split(",") if p.strip()]

        if rt == "board_column" and source_status:
            if source_status.lower() in patterns:
                return rule["phase_id"]

        elif rt == "keyword":
            title_lower = title.lower()
            if any(kw in title_lower for kw in patterns):
                return rule["phase_id"]

        elif rt == "iteration_path" and iteration_path:
            iter_lower = iteration_path.lower()
            if any(pat in iter_lower for pat in patterns):
                return rule["phase_id"]

    return None


async def _load_rules_flat(
    db: AsyncSession, project_id: str, org_id: str
) -> list[dict]:
    """Load all rules for a project as flat dicts for the resolution engine."""
    stmt = (
        select(
            PhaseAssignmentRule.id,
            PhaseAssignmentRule.phase_id,
            PhaseAssignmentRule.rule_type,
            PhaseAssignmentRule.pattern,
            PhaseAssignmentRule.priority,
            ProjectPhase.sort_order,
        )
        .join(ProjectPhase, ProjectPhase.id == PhaseAssignmentRule.phase_id)
        .where(
            ProjectPhase.project_id == project_id,
            ProjectPhase.organization_id == org_id,
        )
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": r.id,
            "phase_id": r.phase_id,
            "rule_type": r.rule_type,
            "pattern": r.pattern,
            "priority": r.priority,
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


async def _seed_defaults(
    db: AsyncSession, project_id: str, org_id: str
) -> list[ProjectPhase]:
    """Create the 6 default phases with their keyword rules."""
    phases = []
    for i, defn in enumerate(DEFAULT_PHASES):
        phase = ProjectPhase(
            id=generate_cuid(),
            organization_id=org_id,
            project_id=project_id,
            name=defn["name"],
            slug=defn["slug"],
            color=defn["color"],
            sort_order=i,
            is_default=True,
        )
        db.add(phase)
        phases.append(phase)

        for rule_defn in defn.get("rules", []):
            rule = PhaseAssignmentRule(
                id=generate_cuid(),
                phase_id=phase.id,
                rule_type=rule_defn["rule_type"],
                pattern=rule_defn["pattern"],
                priority=rule_defn.get("priority", 0),
            )
            db.add(rule)

    await db.commit()
    return phases


async def _ensure_board_column_rules(
    db: AsyncSession, project_id: str, org_id: str
) -> int:
    """Ensure default phases have current rules (board_column + updated keywords).

    Handles the case where phases were seeded before board_column rules
    or updated keyword patterns were added to DEFAULT_PHASES.
    """
    # Load existing phases
    phases = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
                ProjectPhase.is_default == True,
            ).order_by(ProjectPhase.sort_order)
        )
    ).scalars().all()

    if not phases:
        return 0

    # Build slug → phase map
    slug_to_phase = {p.slug: p for p in phases}

    # Load existing rules
    phase_ids = [p.id for p in phases]
    existing_rules = (
        await db.execute(
            select(PhaseAssignmentRule).where(
                PhaseAssignmentRule.phase_id.in_(phase_ids)
            )
        )
    ).scalars().all()

    # Index existing rules by (phase_id, rule_type)
    rule_index: dict[tuple[str, str], PhaseAssignmentRule] = {}
    for r in existing_rules:
        rule_index[(r.phase_id, r.rule_type)] = r

    changed = 0
    import logging
    _log = logging.getLogger("phases.ensure_rules")
    for defn in DEFAULT_PHASES:
        phase = slug_to_phase.get(defn["slug"])
        if not phase:
            _log.warning(f"[ensure_rules] slug '{defn['slug']}' not found in existing phases")
            continue

        for rule_defn in defn.get("rules", []):
            key = (phase.id, rule_defn["rule_type"])
            existing = rule_index.get(key)

            if existing:
                # Update pattern if it changed
                if existing.pattern != rule_defn["pattern"]:
                    _log.info(f"[ensure_rules] Updating {phase.slug} {rule_defn['rule_type']}: '{existing.pattern}' → '{rule_defn['pattern']}'")
                    existing.pattern = rule_defn["pattern"]
                    existing.priority = rule_defn.get("priority", 0)
                    changed += 1
            else:
                # Add missing rule
                rule = PhaseAssignmentRule(
                    id=generate_cuid(),
                    phase_id=phase.id,
                    rule_type=rule_defn["rule_type"],
                    pattern=rule_defn["pattern"],
                    priority=rule_defn.get("priority", 0),
                )
                db.add(rule)
                changed += 1

    if changed > 0:
        await db.commit()
    return changed


# ── Endpoints ──


@router.get("/projects/{project_id}/phases")
async def list_phases(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = user["organization_id"]

    # Check if phases exist; auto-seed if not
    count_stmt = select(func.count()).where(
        ProjectPhase.project_id == project_id,
        ProjectPhase.organization_id == org_id,
    )
    count = (await db.execute(count_stmt)).scalar() or 0

    if count == 0:
        await _seed_defaults(db, project_id, org_id)

    # Load phases with feature counts
    stmt = (
        select(
            ProjectPhase,
            func.count(WorkItem.id).label("feature_count"),
        )
        .outerjoin(
            WorkItem,
            (WorkItem.phase_id == ProjectPhase.id)
            & (WorkItem.type.in_(["epic", "feature"])),
        )
        .where(
            ProjectPhase.project_id == project_id,
            ProjectPhase.organization_id == org_id,
        )
        .group_by(ProjectPhase.id)
        .order_by(ProjectPhase.sort_order)
    )
    rows = (await db.execute(stmt)).all()

    # Load rules per phase
    rule_stmt = (
        select(PhaseAssignmentRule)
        .join(ProjectPhase)
        .where(
            ProjectPhase.project_id == project_id,
            ProjectPhase.organization_id == org_id,
        )
        .order_by(PhaseAssignmentRule.priority.desc())
    )
    all_rules = (await db.execute(rule_stmt)).scalars().all()
    rules_by_phase: dict[str, list] = {}
    for r in all_rules:
        rules_by_phase.setdefault(r.phase_id, []).append(
            {
                "id": r.id,
                "phaseId": r.phase_id,
                "ruleType": r.rule_type,
                "pattern": r.pattern,
                "priority": r.priority,
            }
        )

    return [
        {
            "id": phase.id,
            "projectId": phase.project_id,
            "name": phase.name,
            "slug": phase.slug,
            "color": phase.color,
            "sortOrder": phase.sort_order,
            "isDefault": phase.is_default,
            "featureCount": feat_count,
            "rules": rules_by_phase.get(phase.id, []),
        }
        for phase, feat_count in rows
    ]


@router.post("/projects/{project_id}/phases", status_code=201)
async def create_phase(
    project_id: str,
    body: PhaseCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = user["organization_id"]
    slug = _slugify(body.name)

    # Check uniqueness
    existing = (
        await db.execute(
            select(ProjectPhase.id).where(
                ProjectPhase.project_id == project_id,
                ProjectPhase.slug == slug,
            )
        )
    ).scalar()
    if existing:
        raise HTTPException(400, f"Phase with slug '{slug}' already exists")

    # Get max sort_order
    max_order = (
        await db.execute(
            select(func.coalesce(func.max(ProjectPhase.sort_order), -1)).where(
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
            )
        )
    ).scalar()

    phase = ProjectPhase(
        id=generate_cuid(),
        organization_id=org_id,
        project_id=project_id,
        name=body.name,
        slug=slug,
        color=body.color,
        sort_order=(max_order or 0) + 1,
        is_default=False,
    )
    db.add(phase)
    await db.commit()

    return {
        "id": phase.id,
        "projectId": phase.project_id,
        "name": phase.name,
        "slug": phase.slug,
        "color": phase.color,
        "sortOrder": phase.sort_order,
        "isDefault": False,
        "featureCount": 0,
        "rules": [],
    }


@router.patch("/projects/{project_id}/phases/{phase_id}")
async def update_phase(
    project_id: str,
    phase_id: str,
    body: PhaseUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = user["organization_id"]
    phase = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.id == phase_id,
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()

    if not phase:
        raise HTTPException(404, "Phase not found")

    if body.name is not None:
        phase.name = body.name
        phase.slug = _slugify(body.name)
    if body.color is not None:
        phase.color = body.color

    await db.commit()
    return {"ok": True, "id": phase.id, "name": phase.name, "color": phase.color}


@router.delete("/projects/{project_id}/phases/{phase_id}")
async def delete_phase(
    project_id: str,
    phase_id: str,
    body: PhaseDelete = PhaseDelete(),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = user["organization_id"]
    phase = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.id == phase_id,
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()

    if not phase:
        raise HTTPException(404, "Phase not found")

    # Move features to target phase or set to NULL (unassigned)
    await db.execute(
        update(WorkItem)
        .where(WorkItem.phase_id == phase_id)
        .values(phase_id=body.targetPhaseId)
    )

    # Delete phase (rules cascade)
    await db.execute(
        delete(ProjectPhase).where(ProjectPhase.id == phase_id)
    )
    await db.commit()
    return {"ok": True, "deleted": phase_id}


@router.put("/projects/{project_id}/phases/reorder")
async def reorder_phases(
    project_id: str,
    body: PhaseReorder,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = user["organization_id"]
    for i, pid in enumerate(body.phaseIds):
        await db.execute(
            update(ProjectPhase)
            .where(
                ProjectPhase.id == pid,
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
            )
            .values(sort_order=i)
        )
    await db.commit()
    return {"ok": True}


# ── Rules ──


@router.get("/projects/{project_id}/phases/{phase_id}/rules")
async def list_rules(
    project_id: str,
    phase_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(PhaseAssignmentRule)
        .where(PhaseAssignmentRule.phase_id == phase_id)
        .order_by(PhaseAssignmentRule.priority.desc())
    )
    rules = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "phaseId": r.phase_id,
            "ruleType": r.rule_type,
            "pattern": r.pattern,
            "priority": r.priority,
        }
        for r in rules
    ]


@router.post("/projects/{project_id}/phases/{phase_id}/rules", status_code=201)
async def create_rule(
    project_id: str,
    phase_id: str,
    body: RuleCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.ruleType not in ("keyword", "board_column", "iteration_path"):
        raise HTTPException(400, f"Invalid rule_type: {body.ruleType}")

    rule = PhaseAssignmentRule(
        id=generate_cuid(),
        phase_id=phase_id,
        rule_type=body.ruleType,
        pattern=body.pattern,
        priority=body.priority,
    )
    db.add(rule)
    await db.commit()
    return {
        "id": rule.id,
        "phaseId": rule.phase_id,
        "ruleType": rule.rule_type,
        "pattern": rule.pattern,
        "priority": rule.priority,
    }


@router.delete("/projects/{project_id}/phases/rules/{rule_id}")
async def delete_rule(
    project_id: str,
    rule_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        delete(PhaseAssignmentRule).where(PhaseAssignmentRule.id == rule_id)
    )
    await db.commit()
    return {"ok": True, "deleted": rule_id}


# ── Manual phase assignment ──


@router.patch("/work-items/{item_id}/phase")
async def assign_phase(
    item_id: str,
    body: ManualPhaseAssign,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(WorkItem).where(WorkItem.id == item_id).values(phase_id=body.phaseId)
    )
    await db.commit()
    return {"ok": True, "itemId": item_id, "phaseId": body.phaseId}


# ── Source status refresh from ADO/Jira ──


async def _refresh_source_status_from_board(
    db: AsyncSession, project_id: str, org_id: str
) -> int:
    """Fetch board columns from ADO/Jira for all features and update source_status.

    Returns the number of features whose source_status was updated.
    """
    from ..models.imported_project import ImportedProject
    from ..models.tool_connection import ToolConnection

    proj = (
        await db.execute(
            select(ImportedProject).where(
                ImportedProject.id == project_id,
                ImportedProject.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not proj:
        return 0

    conn = (
        await db.execute(
            select(ToolConnection).where(
                ToolConnection.organization_id == org_id,
                ToolConnection.source_tool.in_(["ado", "jira"]),
            )
        )
    ).scalar_one_or_none()
    if not conn:
        return 0

    updated = 0

    if conn.source_tool == "ado":
        updated = await _refresh_ado_source_status(db, conn, proj, org_id)

    return updated


async def _refresh_ado_source_status(
    db: AsyncSession, conn, proj, org_id: str
) -> int:
    """Fetch System.BoardColumn from ADO for all features and update source_status."""
    import httpx
    from ..routers.integrations.ado import _get_ado_auth_info, _get_valid_access_token

    try:
        org_url, auth_header = _get_ado_auth_info(conn)
        config = conn.config or {}
        auth_method = config.get("auth_method", "oauth2")

        if auth_method == "oauth2":
            access_token = await _get_valid_access_token(db, conn)
        else:
            access_token = ""

        # Load all features for this project from DB
        features = (
            await db.execute(
                select(WorkItem).where(
                    WorkItem.organization_id == org_id,
                    WorkItem.imported_project_id == proj.id,
                    WorkItem.type.in_(["epic", "feature"]),
                )
            )
        ).scalars().all()

        if not features:
            return 0

        # Get external IDs → DB feature map
        ext_map = {f.external_id: f for f in features if f.external_id}
        if not ext_map:
            return 0

        # Batch fetch from ADO with System.BoardColumn
        ext_ids = list(ext_map.keys())
        headers = {}
        if auth_method == "oauth2":
            headers["Authorization"] = f"Bearer {access_token}"
        elif auth_header:
            headers["Authorization"] = auth_header

        updated = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(0, len(ext_ids), 200):
                chunk = ext_ids[i : i + 200]
                ids_str = ",".join(chunk)
                url = (
                    f"{org_url}/_apis/wit/workitems?ids={ids_str}"
                    f"&fields=System.Id,System.State,System.BoardColumn"
                    f"&api-version=7.1"
                )
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                for item in data.get("value", []):
                    ext_id = str(item.get("id", ""))
                    fields = item.get("fields", {})
                    board_col = fields.get("System.BoardColumn", "")
                    state = fields.get("System.State", "")
                    source_status = board_col if board_col else state

                    if ext_id in ext_map and source_status:
                        feat = ext_map[ext_id]
                        if feat.source_status != source_status:
                            feat.source_status = source_status
                            updated += 1

        if updated > 0:
            await db.commit()
        return updated
    except Exception:
        return 0


# ── Bulk reassignment ──


@router.post("/projects/{project_id}/phases/reassign")
async def reassign_all(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-run all assignment rules for features.

    First refreshes source_status from ADO/Jira board columns (if connected),
    then runs rules to assign features to phases.  Re-assigns ALL features
    (clears manual overrides) so the PO sees a fresh distribution.
    """
    org_id = user["organization_id"]

    # ── Step 0: Ensure board_column rules exist on default phases ──
    await _ensure_board_column_rules(db, project_id, org_id)

    # ── Step 1: Refresh source_status from ADO/Jira ──
    refreshed = await _refresh_source_status_from_board(db, project_id, org_id)

    # ── Step 2: Load rules ──
    rules = await _load_rules_flat(db, project_id, org_id)
    if not rules:
        return {"ok": True, "assigned": 0, "refreshed": refreshed}

    # ── Step 3: Load ALL features (not just unassigned) and reassign ──
    stmt = select(WorkItem).where(
        WorkItem.organization_id == org_id,
        WorkItem.imported_project_id == project_id,
        WorkItem.type.in_(["epic", "feature"]),
    )
    features = (await db.execute(stmt)).scalars().all()

    assigned = 0
    for f in features:
        phase_id = resolve_phase_for_feature(
            title=f.title,
            source_status=f.source_status,
            iteration_path=None,
            rules=rules,
            item_type=getattr(f, "type", None),
        )
        if phase_id:
            f.phase_id = phase_id
            assigned += 1
        else:
            f.phase_id = None  # Clear stale assignment

    await db.commit()
    return {"ok": True, "assigned": assigned, "refreshed": refreshed}


# ── Import from ADO/Jira board ──


@router.post("/projects/{project_id}/phases/import-from-board")
async def import_from_board(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete all existing phases for this project, then import board columns
    from the connected ADO/Jira integration as new phases with board_column rules.
    """
    org_id = user["organization_id"]

    # Find the source tool for this project
    from ..models.imported_project import ImportedProject
    from ..models.tool_connection import ToolConnection

    proj = (
        await db.execute(
            select(ImportedProject).where(
                ImportedProject.id == project_id,
                ImportedProject.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "Project not found")

    # Get the tool connection for the org
    conn = (
        await db.execute(
            select(ToolConnection).where(
                ToolConnection.organization_id == org_id,
                ToolConnection.source_tool.in_(["ado", "jira"]),
            )
        )
    ).scalar_one_or_none()
    if not conn:
        raise HTTPException(400, "No active ADO or Jira connection found")

    # Fetch board columns
    columns: list[str] = []

    if conn.source_tool == "ado":
        columns = await _fetch_ado_board_columns(conn, proj)
    elif conn.source_tool == "jira":
        columns = await _fetch_jira_board_columns(conn, proj)

    if not columns:
        raise HTTPException(400, "Could not fetch board columns")

    # Delete all existing phases for this project
    existing_ids = (
        await db.execute(
            select(ProjectPhase.id).where(
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
            )
        )
    ).scalars().all()

    if existing_ids:
        # Unassign all features first
        await db.execute(
            update(WorkItem)
            .where(WorkItem.phase_id.in_(existing_ids))
            .values(phase_id=None)
        )
        await db.execute(
            delete(ProjectPhase).where(ProjectPhase.id.in_(existing_ids))
        )

    # Create phases from board columns
    # Assign colors from a palette
    palette = [
        "#8b5cf6", "#3b82f6", "#06b6d4", "#f59e0b",
        "#f97316", "#22c55e", "#ec4899", "#ef4444",
        "#14b8a6", "#a855f7", "#6366f1", "#84cc16",
    ]
    created_phases = []
    for i, col_name in enumerate(columns):
        phase = ProjectPhase(
            id=generate_cuid(),
            organization_id=org_id,
            project_id=project_id,
            name=col_name,
            slug=_slugify(col_name),
            color=palette[i % len(palette)],
            sort_order=i,
            is_default=False,
        )
        db.add(phase)

        # Auto-create board_column rule matching source_status
        rule = PhaseAssignmentRule(
            id=generate_cuid(),
            phase_id=phase.id,
            rule_type="board_column",
            pattern=col_name,
            priority=10,  # Higher priority than keyword rules
        )
        db.add(rule)
        created_phases.append({"name": col_name, "id": phase.id})

    await db.commit()

    # Auto-assign features using the new rules
    rules = await _load_rules_flat(db, project_id, org_id)
    stmt = select(WorkItem).where(
        WorkItem.organization_id == org_id,
        WorkItem.imported_project_id == project_id,
        WorkItem.type.in_(["epic", "feature"]),
    )
    features = (await db.execute(stmt)).scalars().all()
    assigned = 0
    for f in features:
        pid = resolve_phase_for_feature(
            title=f.title,
            source_status=f.source_status,
            iteration_path=None,
            rules=rules,
            item_type=getattr(f, "type", None),
        )
        if pid:
            f.phase_id = pid
            assigned += 1
    await db.commit()

    return {
        "ok": True,
        "source": conn.source_tool,
        "phases": created_phases,
        "featuresAssigned": assigned,
    }


async def _fetch_ado_board_columns(conn, proj) -> list[str]:
    """Fetch board column names from ADO Boards API."""
    import httpx

    access_token = conn.access_token
    org_url = conn.org_url  # e.g. https://dev.azure.com/OrgName
    project_name = proj.external_name or proj.name

    # Try fetching the board for the project
    boards_url = f"{org_url}/{project_name}/_apis/work/boards?api-version=7.0"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(boards_url, headers=headers)
            if resp.status_code != 200:
                return _ado_fallback_columns()

            boards = resp.json().get("value", [])
            if not boards:
                return _ado_fallback_columns()

            # Pick the first board (usually "Stories" or "Backlog items")
            board_name = boards[0].get("name", "Stories")
            cols_url = (
                f"{org_url}/{project_name}/_apis/work/boards"
                f"/{board_name}/columns?api-version=7.0"
            )
            resp2 = await client.get(cols_url, headers=headers)
            if resp2.status_code != 200:
                return _ado_fallback_columns()

            cols = resp2.json().get("value", [])
            return [c["name"] for c in cols if c.get("name")]
    except Exception:
        return _ado_fallback_columns()


def _ado_fallback_columns() -> list[str]:
    return ["New", "Ready", "In Progress", "Testing", "Migrate", "Closed"]


async def _fetch_jira_board_columns(conn, proj) -> list[str]:
    """Fetch board column names from Jira Board API."""
    import httpx

    access_token = conn.access_token
    cloud_url = conn.org_url  # e.g. https://yoursite.atlassian.net

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Find boards for the project
            boards_url = (
                f"{cloud_url}/rest/agile/1.0/board"
                f"?projectKeyOrId={proj.external_id}"
            )
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = await client.get(boards_url, headers=headers)
            if resp.status_code != 200:
                return ["To Do", "In Progress", "In Review", "Done"]

            boards = resp.json().get("values", [])
            if not boards:
                return ["To Do", "In Progress", "In Review", "Done"]

            board_id = boards[0]["id"]
            config_url = (
                f"{cloud_url}/rest/agile/1.0/board/{board_id}/configuration"
            )
            resp2 = await client.get(config_url, headers=headers)
            if resp2.status_code != 200:
                return ["To Do", "In Progress", "In Review", "Done"]

            columns = resp2.json().get("columnConfig", {}).get("columns", [])
            return [c["name"] for c in columns if c.get("name")]
    except Exception:
        return ["To Do", "In Progress", "In Review", "Done"]

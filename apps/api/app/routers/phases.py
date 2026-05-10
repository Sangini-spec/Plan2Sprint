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
    # Hotfix 17 — cloud-native ordering. Deployment now comes BEFORE UAT
    # because in cloud-deployed apps the UAT site is something you have
    # to deploy first; users can only run acceptance tests on a deployed
    # environment. Old ordering (UAT before Deployment) reflected the
    # pre-cloud world where UAT happened in a permanently-running staging
    # environment and Deployment meant production release.
    #
    # Existing projects with the default ordering get migrated to this
    # new ordering by alembic migration ``a7c4e1d2b9f3``. Projects that
    # have manually-customised sort_orders (drag-reordered phases) are
    # left alone.
    {
        "name": "Deployment & Launch",
        "slug": "deployment-launch",
        "color": "#22c55e",
        "sort_order": 4,
        "rules": [
            {"rule_type": "keyword", "pattern": "deploy,launch,migration,release,go-live", "priority": 0},
            {"rule_type": "board_column", "pattern": "closed,done", "priority": 10},
        ],
    },
    {
        "name": "UAT & Staging",
        "slug": "uat-staging",
        "color": "#f97316",
        "sort_order": 5,
        "rules": [
            {"rule_type": "keyword", "pattern": "uat,staging,acceptance,user acceptance,validation", "priority": 0},
            {"rule_type": "board_column", "pattern": "migrate,uat,staging", "priority": 10},
        ],
    },
    {
        # Final "Ready" phase — the product is fully ready for customers across
        # QA, infrastructure, approvals. In Raw mode the date lines up with the
        # latest ADO/Jira feature end; in AI/Rebalanced modes it tracks the
        # project's target_launch_date. If no end date is known anywhere the UI
        # falls back to a "TBD" label rather than inventing a value.
        "name": "Ready",
        "slug": "ready",
        "color": "#10b981",
        "sort_order": 6,
        "rules": [
            {"rule_type": "keyword", "pattern": "ready,handoff,hand-off,sign-off,customer,ga,general availability", "priority": 0},
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
    """Ensure phases have current rules (board_column + updated keywords).

    Handles the case where phases were seeded before board_column rules
    or updated keyword patterns were added to DEFAULT_PHASES.

    Hotfix 18 — used to filter on ``is_default == True``, which silently
    skipped any phase created via Import-from-Board (those are
    ``is_default=False``). Result: their keyword/board_column rules
    never got refreshed, so newer titles wouldn't match and features
    fell into Unassigned. We now match by ``slug`` against
    DEFAULT_PHASES regardless of the ``is_default`` flag — if a phase
    has the same slug as a default phase, its rules get refreshed too.
    Phases with custom slugs (genuine user customisations) are ignored
    by the slug lookup, so we never overwrite intentionally-different
    rules.
    """
    # Load all phases for this project — we'll filter to those whose slugs
    # match DEFAULT_PHASES below, regardless of the is_default flag.
    phases = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
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

    # Hotfix 23 — match by the project's source_tool, not "any of ADO/JIRA".
    # When an org has BOTH ADO and Jira connected, the previous
    # ``scalar_one_or_none()`` on a 2-row result raised
    # ``MultipleResultsFound`` and crashed the whole reassign endpoint.
    # Now we pick the connection whose tool matches the project's
    # source_tool; falls back to ANY ado/jira connection if the project's
    # source_tool is unset (legacy data).
    proj_tool_upper = (proj.source_tool or "").upper()
    conn_query = select(ToolConnection).where(
        ToolConnection.organization_id == org_id,
        func.upper(ToolConnection.source_tool).in_(["ADO", "JIRA"]),
    )
    if proj_tool_upper in ("ADO", "JIRA"):
        conn_query = conn_query.where(
            func.upper(ToolConnection.source_tool) == proj_tool_upper
        )
    # Use ``.first()`` so duplicate rows (legacy reconnect artefacts) don't
    # crash; ordering is implementation-defined but consistent enough that
    # any ADO connection for an ADO project gets us the right token.
    conn = (await db.execute(conn_query)).scalars().first()
    if not conn:
        return 0

    updated = 0

    if (conn.source_tool or "").upper() == "ADO":
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

    # Hotfix 3b — load phases ordered by sort_order so we know which one
    # to use as the default fallback when no rule matches. Same logic as
    # import-from-board so re-running rules can't move a feature OUT of
    # a phase and into Unassigned.
    phase_rows = (
        await db.execute(
            select(ProjectPhase)
            .where(
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
            )
            .order_by(ProjectPhase.sort_order.asc())
        )
    ).scalars().all()
    first_phase_id = phase_rows[0].id if phase_rows else None
    phase_meta = [(p.id, (p.name or "")) for p in phase_rows]

    # Hotfix 20 — when "Re-run Rules" runs, also fire the AI classifier
    # for any features rules don't match. The user explicitly clicked
    # this button so a few seconds of LLM work is acceptable; it's a
    # foreground manual action, not a hot dashboard read. AI verdicts
    # get cached on the work item the same way as the background path.
    from ..services.ai_phase_classifier import classify_and_cache
    phases_for_ai = [
        {"id": p.id, "slug": p.slug, "name": p.name}
        for p in phase_rows
    ]

    # Hotfix 24c — per-feature resolution audit trail. We've had bug
    # reports of "Re-run Rules ran but Unassigned section is unchanged"
    # without enough info to diagnose. The list below records WHICH tier
    # placed each feature so we can return it (and log it) and tell
    # whether AI fired, rules matched, or fallback took over.
    import logging as _log
    _log_phases = _log.getLogger("phases.reassign")
    import asyncio

    # Pass 1 — synchronous tiers (rules + status_token). These are
    # microsecond-scale; do them inline. Track which features still
    # need AI classification so we can fire those in parallel below.
    pending_ai: list = []  # features that fell through tiers 1+2
    placeholder: dict[str, str] = {}  # feature.id -> tier_name (rules/status_token)
    placement: dict[str, str | None] = {}  # feature.id -> phase_id
    for f in features:
        phase_id = resolve_phase_for_feature(
            title=f.title,
            source_status=f.source_status,
            iteration_path=None,
            rules=rules,
            item_type=getattr(f, "type", None),
        )
        if phase_id:
            placement[f.id] = phase_id
            placeholder[f.id] = "rules"
            continue
        if f.status:
            status_token = (f.status or "").upper()
            for pid, pname in phase_meta:
                col_upper = pname.upper().replace(" ", "")
                if col_upper and (status_token in col_upper or col_upper in status_token):
                    placement[f.id] = pid
                    placeholder[f.id] = "status_token"
                    break
        if f.id in placement:
            continue
        # Needs AI classification.
        pending_ai.append(f)

    # Pass 2 — AI classification in PARALLEL. Hotfix 28: was sequential,
    # which meant 10 unmatched features × ~5s/call = 50s, exceeding most
    # proxy timeouts. asyncio.gather fans them out so total wall time is
    # roughly the slowest individual call (~5-10s).
    ai_results: dict[str, str | None] = {}
    ai_errors: set[str] = set()
    if pending_ai and phases_for_ai:
        async def _classify_one(feat):
            try:
                got = await classify_and_cache(feat, phases_for_ai, db)
                return feat.id, got, None
            except Exception as e:  # noqa: BLE001
                return feat.id, None, str(e)[:120]

        results = await asyncio.gather(
            *[_classify_one(feat) for feat in pending_ai],
            return_exceptions=False,
        )
        for fid, phase_id, err in results:
            if err is not None:
                ai_errors.add(fid)
            else:
                ai_results[fid] = phase_id

    # Pass 3 — apply AI results, then fallback for anything still missing.
    audit: list[dict] = []
    assigned = 0
    ai_assigned = 0
    fallback_assigned = 0
    for f in features:
        tier = "none"
        if f.id in placement:
            phase_id = placement[f.id]
            tier = placeholder[f.id]
        else:
            ai_phase_id = ai_results.get(f.id)
            if ai_phase_id:
                phase_id = ai_phase_id
                tier = "ai"
                ai_assigned += 1
            elif f.id in ai_errors:
                phase_id = None
                tier = "ai_error"
            else:
                phase_id = None
        if phase_id:
            f.phase_id = phase_id
            assigned += 1
        elif first_phase_id:
            f.phase_id = first_phase_id
            fallback_assigned += 1
            tier = "fallback_first_phase"
        else:
            f.phase_id = None
            tier = "unassigned_no_phases"
        audit.append({
            "id": f.id,
            "title": (f.title or "")[:80],
            "status": f.status,
            "sourceStatus": f.source_status,
            "tier": tier,
            "phaseId": f.phase_id,
        })

    # Log a summary line so we can grep Container App logs.
    tier_counts: dict[str, int] = {}
    for a in audit:
        tier_counts[a["tier"]] = tier_counts.get(a["tier"], 0) + 1
    _log_phases.info(
        f"[reassign] project={project_id} total={len(features)} "
        f"tier_counts={tier_counts}"
    )

    await db.commit()
    return {
        "ok": True,
        "assigned": assigned,
        "aiAssigned": ai_assigned,
        "fallbackAssigned": fallback_assigned,
        "refreshed": refreshed,
        # Hotfix 24c — per-feature audit so DevTools network tab shows
        # exactly what tier won for each feature. Caps to first 100
        # entries so the response payload doesn't balloon on huge
        # projects.
        "tierCounts": tier_counts,
        "audit": audit[:100],
    }


# ── Import from ADO/Jira board ──


@router.get("/projects/{project_id}/phases/board-preview")
async def board_preview(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read-only preview — returns the column names that the actual import
    would create as phases, WITHOUT touching any DB state.

    Frontend flow: click "Import from ADO/Jira Board" → this endpoint
    returns the columns → UI shows a confirmation panel listing them →
    user clicks "Replace phases" → POST /import-from-board commits the
    swap.
    """
    org_id = user["organization_id"]
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

    # CASE-INSENSITIVE source_tool lookup. The OAuth callbacks persist
    # ``ToolConnection.source_tool`` / ``ImportedProject.source_tool`` as
    # uppercase ("ADO", "JIRA") while older code paths use lowercase. We
    # normalise both sides via UPPER() so the row is always found
    # regardless of how it was stored. Prefers the connection that
    # matches the project's tool (relevant when an org has BOTH Jira
    # and ADO connected).
    proj_tool_upper = (proj.source_tool or "").upper()
    conn_query = select(ToolConnection).where(
        ToolConnection.organization_id == org_id,
        func.upper(ToolConnection.source_tool).in_(["ADO", "JIRA"]),
    )
    if proj_tool_upper in ("ADO", "JIRA"):
        conn_query = conn_query.where(
            func.upper(ToolConnection.source_tool) == proj_tool_upper
        )
    conn = (await db.execute(conn_query)).scalar_one_or_none()
    if not conn:
        tool_label = (
            proj_tool_upper if proj_tool_upper in ("ADO", "JIRA") else "ADO / Jira"
        )
        raise HTTPException(
            400,
            f"No active {tool_label} connection found. Connect {tool_label} from the Connect Tools menu to import board columns.",
        )

    conn_tool_upper = (conn.source_tool or "").upper()
    columns: list[str] = []
    if conn_tool_upper == "ADO":
        columns = await _fetch_ado_board_columns(conn, proj, db)
    elif conn_tool_upper == "JIRA":
        columns = await _fetch_jira_board_columns(conn, proj)

    if not columns:
        raise HTTPException(400, "Could not fetch board columns")

    # Return preview with the existing-phase count so the UI can show
    # "Replace your current 7 phases with these 5 columns" copy.
    existing_count = (
        await db.execute(
            select(func.count(ProjectPhase.id)).where(
                ProjectPhase.project_id == project_id,
                ProjectPhase.organization_id == org_id,
            )
        )
    ).scalar() or 0

    return {
        "source": conn_tool_upper.lower(),  # always lowercase to UI
        "columns": columns,
        "existingPhaseCount": existing_count,
    }


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

    # CASE-INSENSITIVE source_tool lookup — see board-preview endpoint
    # for the rationale. Connections + projects are persisted as "ADO" /
    # "JIRA" but several call-sites historically used the lowercase
    # form, so we normalise both sides.
    proj_tool_upper = (proj.source_tool or "").upper()
    conn_query = select(ToolConnection).where(
        ToolConnection.organization_id == org_id,
        func.upper(ToolConnection.source_tool).in_(["ADO", "JIRA"]),
    )
    if proj_tool_upper in ("ADO", "JIRA"):
        conn_query = conn_query.where(
            func.upper(ToolConnection.source_tool) == proj_tool_upper
        )
    conn = (await db.execute(conn_query)).scalar_one_or_none()
    if not conn:
        tool_label = (
            proj_tool_upper if proj_tool_upper in ("ADO", "JIRA") else "ADO / Jira"
        )
        raise HTTPException(
            400,
            f"No active {tool_label} connection found. Connect {tool_label} from the Connect Tools menu to import board columns.",
        )

    # Fetch board columns
    conn_tool_upper = (conn.source_tool or "").upper()
    columns: list[str] = []

    if conn_tool_upper == "ADO":
        columns = await _fetch_ado_board_columns(conn, proj, db)
    elif conn_tool_upper == "JIRA":
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

    # Hotfix 3b — default-phase fallback. ADO features (parent items) often
    # don't appear on the Kanban board, so System.BoardColumn is empty and
    # source_status falls back to System.State (e.g. "Active"). If the
    # imported board doesn't have a phase named "Active", the feature would
    # land in the "Unassigned" bucket — confusing for POs who already see
    # an assignee on the row. We fall back to:
    #   1) phase that matches the normalised status (DONE / IN_PROGRESS / …)
    #      against the column name in any reasonable way, then
    #   2) the FIRST phase (sort_order = 0), so every feature is visible
    #      on the Gantt and can be dragged to the right swimlane manually.
    first_phase_id = created_phases[0]["id"] if created_phases else None
    assigned = 0
    fallback_assigned = 0
    for f in features:
        pid = resolve_phase_for_feature(
            title=f.title,
            source_status=f.source_status,
            iteration_path=None,
            rules=rules,
            item_type=getattr(f, "type", None),
        )
        # Secondary attempt: try matching the normalised work-item status
        # against any phase whose column name contains that token. Catches
        # the common case where source_status is empty but status is set
        # (e.g. ADO features parented above the board).
        if not pid and f.status:
            status_token = (f.status or "").upper()
            for p in created_phases:
                col_upper = (p["name"] or "").upper().replace(" ", "")
                if col_upper and (status_token in col_upper or col_upper in status_token):
                    pid = p["id"]
                    break
        if pid:
            f.phase_id = pid
            assigned += 1
        elif first_phase_id:
            # Last resort — first phase. Better than dumping into Unassigned.
            f.phase_id = first_phase_id
            fallback_assigned += 1
    await db.commit()

    return {
        "ok": True,
        "source": (conn.source_tool or "").lower(),
        "phases": created_phases,
        "featuresAssigned": assigned,
        "fallbackAssigned": fallback_assigned,
    }


async def _fetch_ado_board_columns(conn, proj, db: AsyncSession | None = None) -> list[str]:
    """Fetch board column names from ADO Boards API.

    The previous implementation read ``conn.org_url`` and ``conn.access_token``
    directly — both are wrong. ``ToolConnection`` has no ``org_url`` attribute
    (the org URL lives in ``conn.config["org_url"]``), and the access token is
    stored encrypted, so it can't be sent verbatim as a Bearer header. We
    delegate to the same auth helpers ``_refresh_ado_source_status`` already
    uses, so token refresh + PAT fallback are handled centrally.

    Wraps the entire body in a try/except so any unexpected upstream change
    (404 project, network error, malformed json) degrades to the fallback
    columns instead of bubbling up as a 500 — the PO can still see the
    sheet and pick a connection / phase set.
    """
    import httpx
    from ..routers.integrations.ado import _get_ado_auth_info, _get_valid_access_token

    try:
        org_url, auth_header = _get_ado_auth_info(conn)
        config = conn.config or {}
        auth_method = config.get("auth_method", "oauth2")

        headers: dict[str, str] = {"Accept": "application/json"}
        if auth_method == "oauth2" and db is not None:
            access_token = await _get_valid_access_token(db, conn)
            headers["Authorization"] = f"Bearer {access_token}"
        elif auth_header:
            headers["Authorization"] = auth_header
        else:
            # Can't authenticate without a db handle for OAuth refresh.
            return _ado_fallback_columns()

        project_name = (
            getattr(proj, "external_name", None)
            or getattr(proj, "name", None)
            or proj.external_id
        )

        boards_url = f"{org_url}/{project_name}/_apis/work/boards?api-version=7.0"
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
    """Fetch board column names from Jira Board API.

    Same shape of bug as the ADO version — ``conn.org_url`` doesn't exist
    on the model, and the bearer token is encrypted on disk. We pull the
    URL out of ``conn.config`` and the helpers / decryption out of the
    Jira router so everything stays consistent with the rest of the
    Jira flows.
    """
    import httpx

    try:
        config = conn.config or {}
        # Jira's URL field in config is variously named — check both.
        cloud_url = (
            config.get("cloud_url")
            or config.get("site_url")
            or config.get("org_url")
        )
        if not cloud_url:
            return ["To Do", "In Progress", "In Review", "Done"]

        # Decrypt the OAuth access token (stored encrypted at rest).
        try:
            from ..routers.integrations.jira import decrypt_token  # type: ignore
            access_token = decrypt_token(conn.access_token)
        except Exception:
            try:
                from ..auth.encryption import decrypt_token  # type: ignore
                access_token = decrypt_token(conn.access_token)
            except Exception:
                # Last-ditch: assume it's already plaintext.
                access_token = conn.access_token

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            boards_url = (
                f"{cloud_url}/rest/agile/1.0/board"
                f"?projectKeyOrId={proj.external_id}"
            )
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

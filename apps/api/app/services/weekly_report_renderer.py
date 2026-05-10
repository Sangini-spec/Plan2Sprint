"""
Weekly Stakeholder Report — PDF renderer (reportlab).

One-page, compact, visually scannable report modeled after a real-world
enterprise project-status format:

  - Header strip: project name / # / stage / status
  - Timeline bar: horizontal milestone dots (Kick-off → Hypercare style)
  - Three cards: Team Health · Progress · Risks
  - Upcoming milestones list
  - Footer: timestamp

Exposed:
    render_weekly_report_pdf(data: WeeklyReportData) -> bytes
    collect_weekly_report_data(db, org_id, project_id) -> WeeklyReportData
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------

@dataclass
class TimelineStage:
    name: str
    date_label: str  # e.g. "10/27/25" — human-readable
    state: str       # "done" | "current" | "future"


@dataclass
class MilestoneRow:
    name: str
    date_label: str
    status_color: tuple  # RGB 0-1


@dataclass
class RiskRow:
    severity: str  # "GREEN" | "AMBER" | "RED"
    title: str


@dataclass
class PillarScore:
    label: str
    value: int
    severity: str


@dataclass
class WeeklyReportData:
    project_name: str
    project_code: str                # external_id or short id
    stage_label: str                 # e.g. "Development"
    status_label: str                # "On Time" | "At Risk" | "Delayed"
    status_severity: str             # "GREEN"/"AMBER"/"RED"

    overall_completion_pct: int      # 0..100 (portfolio SP completion)
    progress_narrative: str          # 1-2 sentences, AI or rule-based

    timeline: list[TimelineStage] = field(default_factory=list)

    # Team health card
    team_health_score: int = 0
    team_health_severity: str = "AMBER"
    team_health_label: str = "At Risk"
    pillars: list[PillarScore] = field(default_factory=list)

    # Progress card. ``predictability_pct`` is float (one-decimal) post
    # Hotfix 10 — the score formula now returns 96.4-style values rather
    # than a rounded int. Comparisons + str() rendering still work.
    predictability_pct: Optional[float] = None
    current_sprint_name: Optional[str] = None
    current_sprint_pct: Optional[int] = None
    velocity_delta_pct: Optional[int] = None

    # Risks
    risks: list[RiskRow] = field(default_factory=list)

    # Upcoming milestones (next 3-4)
    milestones: list[MilestoneRow] = field(default_factory=list)

    # Footer
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

# Plan2Sprint brand colors (matched to app theme).
BRAND_CYAN = colors.HexColor("#06b6d4")
BRAND_BLUE = colors.HexColor("#3b82f6")
BRAND_TEAL = colors.HexColor("#10b981")
DARK_BG = colors.HexColor("#13131A")
LIGHT_BG = colors.HexColor("#F8F8FC")
SURFACE = colors.HexColor("#FFFFFF")
BORDER = colors.HexColor("#E5E7EB")
# Text palette — intentionally dark so every label stays legible when the PDF
# is shared or printed. Avoid anything lighter than #374151 for live text.
TEXT_PRIMARY = colors.HexColor("#0F172A")   # slate-900
TEXT_SECONDARY = colors.HexColor("#1F2937")  # slate-800
TEXT_TERTIARY = colors.HexColor("#374151")  # slate-700
TEXT_LABEL = colors.HexColor("#4B5563")     # slate-600 — ONLY for small uppercase labels

RAG_GREEN = colors.HexColor("#22C55E")
RAG_AMBER = colors.HexColor("#F59E0B")
RAG_RED = colors.HexColor("#EF4444")


def _rag_color(severity: str):
    s = (severity or "").upper()
    if s == "GREEN":
        return RAG_GREEN
    if s == "AMBER":
        return RAG_AMBER
    if s == "RED":
        return RAG_RED
    return TEXT_TERTIARY


# ---------------------------------------------------------------------------
# Main renderer — takes a landscape A4 page and draws the report
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = landscape(A4)  # 842 x 595 points
MARGIN = 18 * mm
INNER_W = PAGE_W - 2 * MARGIN


def render_weekly_report_pdf(data: WeeklyReportData) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle(f"Plan2Sprint Weekly Report — {data.project_name}")

    # Page background — very subtle off-white
    c.setFillColor(LIGHT_BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    _draw_header(c, data)
    _draw_timeline(c, data)
    _draw_three_cards(c, data)
    _draw_milestones(c, data)
    _draw_footer(c, data)

    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Header strip
# ---------------------------------------------------------------------------

HEADER_H = 46 * mm  # reserved for header + top margin
HEADER_TOP = PAGE_H - MARGIN


def _draw_header(c: rl_canvas.Canvas, d: WeeklyReportData):
    # Big project title, top-left
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(MARGIN, HEADER_TOP - 8 * mm, d.project_name)

    # Stage + Status chips under title
    chip_y = HEADER_TOP - 18 * mm
    x = MARGIN
    x = _draw_chip(c, x, chip_y, "STAGE", d.stage_label, BRAND_BLUE)
    x += 4 * mm
    _draw_chip(c, x, chip_y, "STATUS", d.status_label, _rag_color(d.status_severity))

    # Semicircle completion gauge — top-right (matches the reference PDF)
    _draw_completion_gauge(
        c,
        cx=PAGE_W - MARGIN - 22 * mm,
        cy=HEADER_TOP - 16 * mm,
        radius=16 * mm,
        pct=d.overall_completion_pct,
        accent=_rag_color(d.status_severity),
    )


def _draw_completion_gauge(c: rl_canvas.Canvas, cx: float, cy: float,
                            radius: float, pct: int, accent) -> None:
    """Draw a horseshoe-shaped completion gauge, reference-PDF style."""
    pct = max(0, min(100, int(pct or 0)))
    thickness = 6  # points

    # Background track — full top semicircle, light grey
    c.setLineCap(1)  # round caps
    c.setLineWidth(thickness)
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.arc(cx - radius, cy - radius, cx + radius, cy + radius, 0, 180)

    # Filled portion — from left (180°) travelling clockwise (negative extent)
    if pct > 0:
        c.setStrokeColor(accent)
        c.arc(cx - radius, cy - radius, cx + radius, cy + radius,
              180, -(180 * pct / 100.0))

    # Percentage text — centered inside the arc
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 22)
    label = f"{pct}%"
    c.drawCentredString(cx, cy - 3, label)

    # "Complete" label beneath the number
    c.setFillColor(TEXT_SECONDARY)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(cx, cy - 12, "COMPLETE")


def _draw_chip(c: rl_canvas.Canvas, x: float, y: float, label: str, value: str, accent) -> float:
    """Draw a 'LABEL: value' pill. Returns the x-cursor after the chip."""
    c.setFont("Helvetica-Bold", 7)
    label_w = c.stringWidth(label + ":", "Helvetica-Bold", 7)

    c.setFont("Helvetica-Bold", 9)
    value_w = c.stringWidth(value, "Helvetica-Bold", 9)

    total_w = label_w + 2 * mm + value_w + 8 * mm
    chip_h = 7 * mm

    # Pill background
    c.setFillColor(SURFACE)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.roundRect(x, y - 2 * mm, total_w, chip_h, 3 * mm, fill=1, stroke=1)

    # Colored dot accent
    c.setFillColor(accent)
    c.circle(x + 3.5 * mm, y + 1.5 * mm, 1.2 * mm, fill=1, stroke=0)

    # Label — dark for legibility
    c.setFillColor(TEXT_LABEL)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x + 6 * mm, y + 1 * mm, label + ":")

    # Value
    c.setFillColor(TEXT_PRIMARY)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 6 * mm + label_w + 1 * mm, y + 1 * mm, value)

    return x + total_w


# ---------------------------------------------------------------------------
# Timeline bar
# ---------------------------------------------------------------------------

TIMELINE_TOP = HEADER_TOP - 32 * mm
TIMELINE_H = 22 * mm


def _draw_timeline(c: rl_canvas.Canvas, d: WeeklyReportData):
    if not d.timeline:
        return

    track_y = TIMELINE_TOP - 10 * mm
    left = MARGIN
    right = PAGE_W - MARGIN
    span = right - left

    n = len(d.timeline)
    step = span / max(n - 1, 1) if n > 1 else 0

    # Base track line (grey)
    c.setStrokeColor(BORDER)
    c.setLineWidth(1)
    c.line(left, track_y, right, track_y)

    # Highlighted progress portion (from first to current stage)
    current_idx = next((i for i, s in enumerate(d.timeline) if s.state == "current"), -1)
    if current_idx >= 0:
        progress_x = left + current_idx * step
        c.setStrokeColor(BRAND_CYAN)
        c.setLineWidth(2.5)
        c.line(left, track_y, progress_x, track_y)

    # Stage dots + labels
    for i, stage in enumerate(d.timeline):
        x = left + i * step
        if stage.state == "done":
            fill = BRAND_CYAN
        elif stage.state == "current":
            fill = BRAND_BLUE
        else:
            fill = colors.white

        c.setFillColor(fill)
        c.setStrokeColor(BRAND_BLUE if stage.state != "future" else BORDER)
        c.setLineWidth(1.5)
        c.circle(x, track_y, 2.8 * mm, fill=1, stroke=1)

        # Date label above — dark so it reads clearly
        c.setFillColor(TEXT_SECONDARY)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(x, track_y + 6 * mm, stage.date_label)

        # Stage name below (highlight current, keep others still dark)
        if stage.state == "current":
            c.setFillColor(BRAND_BLUE)
            c.setFont("Helvetica-Bold", 9)
        else:
            # Past stages get primary; future stages slightly dimmer but still dark
            c.setFillColor(TEXT_PRIMARY if stage.state == "done" else TEXT_TERTIARY)
            c.setFont("Helvetica-Bold", 8.5)
        c.drawCentredString(x, track_y - 6 * mm, stage.name)


# ---------------------------------------------------------------------------
# Three cards: Team Health · Progress · Risks
# ---------------------------------------------------------------------------

CARDS_TOP = TIMELINE_TOP - 30 * mm
CARDS_H = 60 * mm


def _draw_three_cards(c: rl_canvas.Canvas, d: WeeklyReportData):
    gap = 4 * mm
    card_w = (INNER_W - 2 * gap) / 3
    x = MARGIN

    _draw_team_health_card(c, x, CARDS_TOP, card_w, CARDS_H, d)
    x += card_w + gap
    _draw_progress_card(c, x, CARDS_TOP, card_w, CARDS_H, d)
    x += card_w + gap
    _draw_risks_card(c, x, CARDS_TOP, card_w, CARDS_H, d)


def _card_frame(c: rl_canvas.Canvas, x: float, y: float, w: float, h: float, accent):
    c.setFillColor(SURFACE)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.roundRect(x, y - h, w, h, 2 * mm, fill=1, stroke=1)
    # Colored accent stripe at top
    c.setFillColor(accent)
    c.roundRect(x, y - 2 * mm, w, 2 * mm, 1 * mm, fill=1, stroke=0)


def _card_title(c: rl_canvas.Canvas, x: float, y: float, title: str):
    c.setFillColor(TEXT_LABEL)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + 4 * mm, y - 7 * mm, title.upper())


def _draw_team_health_card(c, x, y, w, h, d: WeeklyReportData):
    _card_frame(c, x, y, w, h, BRAND_TEAL)
    _card_title(c, x, y, "Team Health")

    # Big score
    score_color = _rag_color(d.team_health_severity)
    c.setFillColor(score_color)
    c.setFont("Helvetica-Bold", 32)
    c.drawString(x + 4 * mm, y - 20 * mm, str(d.team_health_score))
    c.setFillColor(TEXT_TERTIARY)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 4 * mm + c.stringWidth(str(d.team_health_score), "Helvetica-Bold", 32) + 1 * mm,
                 y - 18 * mm, "/ 100")

    # Label
    c.setFillColor(score_color)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + 4 * mm, y - 25 * mm, d.team_health_label.upper())

    # Pillar bars
    pillar_y = y - 31 * mm
    for p in d.pillars[:3]:
        _mini_bar(c, x + 4 * mm, pillar_y, w - 8 * mm, p.label, p.value, p.severity)
        pillar_y -= 7 * mm


def _mini_bar(c, x, y, width, label, value, severity):
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(TEXT_PRIMARY)
    c.drawString(x, y + 2 * mm, label)
    c.setFillColor(_rag_color(severity))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawRightString(x + width, y + 2 * mm, str(value))

    # Bar
    bar_y = y - 0.5 * mm
    c.setFillColor(colors.HexColor("#E5E7EB"))
    c.roundRect(x, bar_y, width, 1.5 * mm, 0.8 * mm, fill=1, stroke=0)
    fill_w = width * max(0, min(100, value)) / 100
    if fill_w > 0:
        c.setFillColor(_rag_color(severity))
        c.roundRect(x, bar_y, fill_w, 1.5 * mm, 0.8 * mm, fill=1, stroke=0)


def _draw_progress_card(c, x, y, w, h, d: WeeklyReportData):
    _card_frame(c, x, y, w, h, BRAND_BLUE)
    _card_title(c, x, y, "Progress")

    # Predictability — big number + % sign
    if d.predictability_pct is not None:
        sev = "GREEN" if d.predictability_pct >= 85 else "AMBER" if d.predictability_pct >= 60 else "RED"
        c.setFillColor(_rag_color(sev))
        c.setFont("Helvetica-Bold", 32)
        c.drawString(x + 4 * mm, y - 20 * mm, f"{d.predictability_pct}")
        w_num = c.stringWidth(str(d.predictability_pct), "Helvetica-Bold", 32)
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(TEXT_SECONDARY)
        c.drawString(x + 4 * mm + w_num + 1 * mm, y - 18 * mm, "%")
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(TEXT_LABEL)
        c.drawString(x + 4 * mm, y - 25 * mm, "PREDICTABILITY")
    else:
        c.setFillColor(TEXT_TERTIARY)
        c.setFont("Helvetica-Bold", 32)
        c.drawString(x + 4 * mm, y - 20 * mm, "—")
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(TEXT_LABEL)
        c.drawString(x + 4 * mm, y - 25 * mm, "PREDICTABILITY")

    # Sub-stats row — each on its own horizontal line with clear labels
    sub_y = y - 32 * mm
    if d.current_sprint_pct is not None and d.current_sprint_name:
        _mini_stat(c, x + 4 * mm, sub_y, w - 8 * mm, "Current sprint",
                   f"{d.current_sprint_pct}%", d.current_sprint_name)
        sub_y -= 6 * mm
    if d.velocity_delta_pct is not None:
        sev = "GREEN" if d.velocity_delta_pct > 5 else "RED" if d.velocity_delta_pct < -5 else "AMBER"
        sign = "+" if d.velocity_delta_pct >= 0 else ""
        _mini_stat(c, x + 4 * mm, sub_y, w - 8 * mm, "Velocity change",
                   f"{sign}{d.velocity_delta_pct}%", "vs last sprint",
                   color=_rag_color(sev))
        sub_y -= 6 * mm

    # Narrative
    narrative_y = y - h + 16 * mm
    c.setFillColor(TEXT_SECONDARY)
    c.setFont("Helvetica-Oblique", 7.5)
    _wrapped_text(c, d.progress_narrative, x + 4 * mm, narrative_y, w - 8 * mm, 9)


def _mini_stat(c, x, y, width, label, value, sublabel, color=None):
    """Compact key:value line. Label on the left, value + sublabel on the right."""
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(TEXT_SECONDARY)
    c.drawString(x, y + 1 * mm, label)

    c.setFont("Helvetica-Bold", 9.5)
    c.setFillColor(color or TEXT_PRIMARY)
    val_w = c.stringWidth(value, "Helvetica-Bold", 9.5)
    value_x = x + width - val_w
    sub_w = c.stringWidth(sublabel or "", "Helvetica", 7)
    if sublabel:
        value_x -= (sub_w + 2 * mm)
    c.drawString(value_x, y + 1 * mm, value)

    if sublabel:
        c.setFont("Helvetica", 7)
        c.setFillColor(TEXT_TERTIARY)
        c.drawString(value_x + val_w + 2 * mm, y + 1 * mm, sublabel)


def _draw_risks_card(c, x, y, w, h, d: WeeklyReportData):
    _card_frame(c, x, y, w, h, RAG_RED)
    _card_title(c, x, y, "Top Risks")

    if not d.risks:
        c.setFillColor(RAG_GREEN)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 4 * mm, y - 14 * mm, "No critical risks flagged.")
        c.setFillColor(TEXT_SECONDARY)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 4 * mm, y - 20 * mm, "All signals green this week.")
        return

    row_y = y - 12 * mm
    for r in d.risks[:3]:
        # Severity dot
        c.setFillColor(_rag_color(r.severity))
        c.circle(x + 5 * mm, row_y, 1.5 * mm, fill=1, stroke=0)

        # Title — dark primary text (keep severity colour only on the dot)
        c.setFillColor(TEXT_PRIMARY)
        c.setFont("Helvetica-Bold", 9)
        title = r.title if len(r.title) <= 55 else r.title[:52] + "..."
        c.drawString(x + 9 * mm, row_y - 0.5 * mm, title)

        row_y -= 12 * mm


# ---------------------------------------------------------------------------
# Milestones strip
# ---------------------------------------------------------------------------

MILESTONES_TOP = CARDS_TOP - CARDS_H - 6 * mm
MILESTONES_H = 36 * mm


def _draw_milestones(c: rl_canvas.Canvas, d: WeeklyReportData):
    if not d.milestones:
        return

    # Container
    c.setFillColor(SURFACE)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.roundRect(MARGIN, MILESTONES_TOP - MILESTONES_H, INNER_W, MILESTONES_H, 2 * mm, fill=1, stroke=1)

    # Accent stripe
    c.setFillColor(BRAND_CYAN)
    c.roundRect(MARGIN, MILESTONES_TOP - 2 * mm, INNER_W, 2 * mm, 1 * mm, fill=1, stroke=0)

    # Title
    c.setFillColor(TEXT_LABEL)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(MARGIN + 4 * mm, MILESTONES_TOP - 7 * mm, "UPCOMING MILESTONES")

    # Up to 4 milestones in a 4-column row. Each milestone gets its own
    # column with a leading dot and wrapped text — names up to 2 lines so we
    # never truncate mid-word (e.g. "AI Sprint Planning & Resource Opti...").
    max_items = min(len(d.milestones), 4)
    col_w = (INNER_W - 8 * mm) / max(max_items, 1)
    inner_text_w = col_w - 8 * mm  # leave room for the dot on the left
    row_y = MILESTONES_TOP - 15 * mm

    for i, m in enumerate(d.milestones[:max_items]):
        cx = MARGIN + 4 * mm + i * col_w

        # Dot — vertically centred on the first text line
        c.setFillColor(m.status_color)
        c.circle(cx + 2 * mm, row_y + 1.5 * mm, 1.4 * mm, fill=1, stroke=0)

        # Name — wrap to max 2 lines, dark primary colour
        c.setFillColor(TEXT_PRIMARY)
        lines = _wrap_lines(c, m.name or "", "Helvetica-Bold", 8.5, inner_text_w, max_lines=2)
        line_y = row_y + 2 * mm
        for ln in lines:
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(cx + 6 * mm, line_y, ln)
            line_y -= 4 * mm

        # Date label sits under the wrapped name
        c.setFillColor(TEXT_SECONDARY)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(cx + 6 * mm, line_y - 0.5 * mm, m.date_label)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

def _draw_footer(c: rl_canvas.Canvas, d: WeeklyReportData):
    y = 10 * mm
    c.setFillColor(TEXT_TERTIARY)
    c.setFont("Helvetica-Bold", 7.5)
    stamp = d.generated_at.strftime("%d %b %Y · %I:%M %p UTC")
    c.drawString(MARGIN, y, f"Last refresh: {stamp}")
    c.drawRightString(PAGE_W - MARGIN, y, "Plan2Sprint · automated weekly report")


# ---------------------------------------------------------------------------
# Line-wrap helper — used for milestone titles. Word-wraps into at most N
# lines and truncates the last line with an ellipsis if it still overflows.
# ---------------------------------------------------------------------------

def _wrap_lines(c, text: str, font: str, size: float, max_width: float,
                max_lines: int = 2) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for w in words:
        candidate = (current + " " + w).strip()
        if c.stringWidth(candidate, font, size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if len(lines) >= max_lines:
            break
        # Start new line; if a single word is wider than the column, force-split
        if c.stringWidth(w, font, size) <= max_width:
            current = w
        else:
            # Trim the word until it fits minus an ellipsis
            trimmed = w
            while trimmed and c.stringWidth(trimmed + "…", font, size) > max_width:
                trimmed = trimmed[:-1]
            lines.append((trimmed or w[:1]) + "…")
            current = ""
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    # If we still have leftover words, append ellipsis to the final line
    consumed = sum(len(ln.split()) for ln in lines)
    if consumed < len(words) and lines:
        last = lines[-1]
        while last and c.stringWidth(last + "…", font, size) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


# ---------------------------------------------------------------------------
# Text wrapping helper
# ---------------------------------------------------------------------------

def _wrapped_text(c, text: str, x: float, y: float, max_width: float, line_height_pt: float):
    words = (text or "").split()
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, "Helvetica-Oblique", 7.5) <= max_width:
            line = test
        else:
            c.drawString(x, y, line)
            y -= line_height_pt
            line = w
            if y < 10 * mm:
                break
    if line:
        c.drawString(x, y, line)


# ---------------------------------------------------------------------------
# Data collection — build WeeklyReportData from live DB/services
# ---------------------------------------------------------------------------

async def collect_weekly_report_data(
    db,
    org_id: str,
    project_id: str,
    project_name: str,
    project_external_id: str,
) -> WeeklyReportData:
    """Gather all the metrics needed for a weekly report for one project."""
    from sqlalchemy import select, func
    from ..models.work_item import WorkItem
    from ..models.iteration import Iteration

    # -------- Portfolio totals --------
    total_sp_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0))
        .where(WorkItem.organization_id == org_id,
               WorkItem.imported_project_id == project_id)
    )
    total_sp = float(total_sp_q.scalar() or 0)
    done_sp_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0))
        .where(WorkItem.organization_id == org_id,
               WorkItem.imported_project_id == project_id,
               WorkItem.status.in_(["DONE", "CLOSED"]))
    )
    done_sp = float(done_sp_q.scalar() or 0)
    overall_pct = int((done_sp / total_sp) * 100) if total_sp > 0 else 0

    # -------- Iterations for timeline + current sprint --------
    iter_q = await db.execute(
        select(Iteration).where(
            Iteration.organization_id == org_id,
            Iteration.imported_project_id == project_id,
        ).order_by(Iteration.start_date)
    )
    iterations = list(iter_q.scalars().all())

    # Timeline stages — use project-plan phases if available; fallback to sprint list
    timeline: list[TimelineStage] = []
    try:
        from ..models.project_phase import ProjectPhase
        phase_q = await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.organization_id == org_id,
                ProjectPhase.project_id == project_id,
            ).order_by(ProjectPhase.sort_order)
        )
        phases = list(phase_q.scalars().all())
    except Exception:
        phases = []

    if phases:
        # Use phases as timeline stages, mark current based on overall_pct
        n = len(phases)
        current_idx = min(int(overall_pct / 100 * n), n - 1)
        for i, p in enumerate(phases):
            state = "done" if i < current_idx else ("current" if i == current_idx else "future")
            timeline.append(TimelineStage(name=p.name, date_label="—", state=state))
    else:
        # Fallback: use sprints
        for i, it in enumerate(iterations[:6]):
            state = (it.state or "").lower()
            if state in ("completed", "closed", "past"):
                tl_state = "done"
            elif state == "active":
                tl_state = "current"
            else:
                tl_state = "future"
            date_str = it.end_date.strftime("%m/%d/%y") if it.end_date else "—"
            timeline.append(TimelineStage(name=it.name, date_label=date_str, state=tl_state))

    # -------- Stage + status labels --------
    current_stage = next((s.name for s in timeline if s.state == "current"), None)
    stage_label = current_stage or (timeline[-1].name if timeline else "Planning")

    # Status inferred from overall_pct + active sprint pace if any
    active = next((it for it in iterations if (it.state or "").lower() == "active"), None)
    status_severity = "GREEN"
    status_label = "On Time"
    if active and active.start_date and active.end_date:
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc)
        total = (active.end_date - active.start_date).total_seconds()
        elapsed = max(0, (now - active.start_date).total_seconds())
        expected_pct = int((elapsed / total) * 100) if total > 0 else 0
        # Approx current sprint actual from work items in this iteration
        q = await db.execute(
            select(
                func.count(WorkItem.id),
                func.count(WorkItem.id).filter(WorkItem.status.in_(["DONE", "CLOSED"])),
            ).where(WorkItem.iteration_id == active.id)
        )
        row = q.first()
        total_items = row[0] or 0
        done_items = row[1] or 0
        actual_pct = int((done_items / total_items) * 100) if total_items > 0 else 0
        delta = actual_pct - expected_pct
        if delta < -15:
            status_severity, status_label = "RED", "Delayed"
        elif delta < -5:
            status_severity, status_label = "AMBER", "At Risk"
        current_sprint_pct = actual_pct
        current_sprint_name = active.name
    else:
        current_sprint_pct = None
        current_sprint_name = None

    # -------- Team health --------
    team_health_score = 0
    team_health_severity = "AMBER"
    team_health_label = "At Risk"
    pillars: list[PillarScore] = []
    pillars_data: dict = {}
    health: Optional[dict] = None
    try:
        from .team_health_engine import get_full_health_dashboard
        health = await get_full_health_dashboard(db, org_id, project_id)
        team_health_score = int(health.get("overallScore") or 0)
        sev = (health.get("overallSeverity") or "AMBER").upper()
        team_health_severity = sev
        team_health_label = "Healthy" if sev == "GREEN" else ("At Risk" if sev == "AMBER" else "Critical")

        pillars_data = health.get("pillars", {})
        if "burnoutRisk" in pillars_data:
            b = pillars_data["burnoutRisk"]
            pillars.append(PillarScore(
                label="Burnout risk",
                value=int(b.get("score") or 0),
                severity=(b.get("severity") or "AMBER").upper(),
            ))
        if "sprintSustainability" in pillars_data:
            s = pillars_data["sprintSustainability"]
            pillars.append(PillarScore(
                label="Sustainability",
                value=int(s.get("score") or 0),
                severity=(s.get("severity") or "AMBER").upper(),
            ))
        if "busFactor" in pillars_data:
            bf = pillars_data["busFactor"]
            pillars.append(PillarScore(
                label="Bus factor",
                value=int(bf.get("score") or 0),
                severity=(bf.get("severity") or "AMBER").upper(),
            ))
    except Exception as e:
        logger.warning("Team health collection failed: %s", e)

    # -------- Predictability & velocity delta --------
    # Uses the same predictability_engine as the Stakeholder dashboard and the
    # /api/analytics endpoint, so the weekly PDF number matches what the PO
    # and stakeholders see in the app. Symmetric (over-delivery penalised),
    # recency-weighted, variance-aware. See services.predictability_engine.
    predictability_pct: Optional[float] = None
    velocity_delta_pct: Optional[int] = None
    try:
        from .predictability_engine import compute_predictability
        pred = await compute_predictability(db, org_id, project_id)
        if pred.score is not None:
            predictability_pct = pred.score
    except Exception as e:  # noqa: BLE001
        logger.warning("Predictability computation failed: %s", e)

    # Velocity delta — unchanged: compare last vs prior sprint's completed SP
    # from the team-health engine's trend.
    try:
        velocity_trend = (
            (health or {}).get("pillars", {})
            .get("sprintSustainability", {})
            .get("metrics", {})
            .get("velocityTrend")
            or []
        )
        if len(velocity_trend) >= 2:
            last = velocity_trend[-1]
            prev = velocity_trend[-2]
            if (prev.get("completed") or 0) > 0:
                velocity_delta_pct = int(
                    ((last.get("completed") or 0) - (prev.get("completed") or 0))
                    / (prev.get("completed") or 1) * 100
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("Velocity delta computation failed: %s", e)

    # Last-resort fallback: use the active sprint's current pace if the
    # engine couldn't produce a number (no completed sprints yet).
    if predictability_pct is None and current_sprint_pct is not None:
        predictability_pct = min(100, current_sprint_pct)

    # -------- Risks --------
    risks: list[RiskRow] = []
    # Blockers
    try:
        from ..models.standup import BlockerFlag, StandupReport
        blocker_q = await db.execute(
            select(func.count(BlockerFlag.id))
            .select_from(BlockerFlag)
            .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
            .where(
                StandupReport.organization_id == org_id,
                BlockerFlag.status != "RESOLVED",
            )
        )
        blocker_count = blocker_q.scalar() or 0
        if blocker_count >= 3:
            risks.append(RiskRow(severity="RED", title=f"{blocker_count} open blockers"))
        elif blocker_count > 0:
            risks.append(RiskRow(severity="AMBER", title=f"{blocker_count} open blocker(s)"))
    except Exception:
        pass
    if status_severity in ("AMBER", "RED") and current_sprint_pct is not None:
        risks.append(RiskRow(severity=status_severity,
                             title=f"Sprint {status_label.lower()} — tracking {current_sprint_pct}% vs plan"))
    # High burnout devs
    try:
        burnout_devs = pillars_data.get("burnoutRisk", {}).get("developers", [])
        red_devs = [d for d in burnout_devs if (d.get("severity") or "").upper() == "RED"]
        if red_devs:
            risks.append(RiskRow(severity="RED",
                                 title=f"{len(red_devs)} developer(s) at burnout risk"))
    except Exception:
        pass

    # -------- Upcoming milestones --------
    milestones: list[MilestoneRow] = []
    try:
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc)

        def _fmt_date_label(target_dt, days_out: int) -> str:
            """Produce a portable date label like '05 May · in 14 days'."""
            date_part = target_dt.strftime("%d %b")
            if days_out < 0:
                return f"{date_part} · {abs(days_out)}d overdue"
            if days_out == 0:
                return f"{date_part} · today"
            if days_out == 1:
                return f"{date_part} · tomorrow"
            return f"{date_part} · in {days_out} days"

        collected: list[tuple[datetime, MilestoneRow]] = []
        # Upcoming sprint end dates
        for it in iterations:
            if it.end_date and it.end_date > now and (it.state or "").lower() != "completed":
                days = (it.end_date - now).days
                color = RAG_RED if days <= 7 else RAG_AMBER if days <= 21 else RAG_GREEN
                collected.append((
                    it.end_date,
                    MilestoneRow(
                        name=f"{it.name} ends",
                        date_label=_fmt_date_label(it.end_date, days),
                        status_color=color,
                    ),
                ))
        # Features / Epics with a planned end date
        feat_q = await db.execute(
            select(WorkItem).where(
                WorkItem.organization_id == org_id,
                WorkItem.imported_project_id == project_id,
                WorkItem.type.in_(["feature", "epic"]),
                WorkItem.planned_end.isnot(None),
                WorkItem.status != "DONE",
            ).order_by(WorkItem.planned_end)
        )
        for f in feat_q.scalars().all():
            days = (f.planned_end - now).days
            color = RAG_RED if days <= 7 else RAG_AMBER if days <= 21 else RAG_GREEN
            collected.append((
                f.planned_end,
                MilestoneRow(
                    name=f.title or "Feature",
                    date_label=_fmt_date_label(f.planned_end, days),
                    status_color=color,
                ),
            ))
        # Sort by actual date, then take the nearest four
        collected.sort(key=lambda pair: pair[0])
        milestones = [row for _, row in collected[:4]]
    except Exception as e:  # noqa: BLE001
        logger.warning("Milestones collection failed: %s", e)

    # -------- Narrative --------
    narrative = _build_narrative(
        overall_pct, status_label, status_severity,
        current_sprint_name, current_sprint_pct,
        predictability_pct, len(risks),
    )

    return WeeklyReportData(
        project_name=project_name,
        project_code=project_external_id[:10] if project_external_id else "—",
        stage_label=stage_label,
        status_label=status_label,
        status_severity=status_severity,
        overall_completion_pct=overall_pct,
        progress_narrative=narrative,
        timeline=timeline,
        team_health_score=team_health_score,
        team_health_severity=team_health_severity,
        team_health_label=team_health_label,
        pillars=pillars,
        predictability_pct=predictability_pct,
        current_sprint_name=current_sprint_name,
        current_sprint_pct=current_sprint_pct,
        velocity_delta_pct=velocity_delta_pct,
        risks=risks,
        milestones=milestones,
    )


def _build_narrative(
    overall_pct: int,
    status_label: str,
    status_severity: str,
    sprint_name: Optional[str],
    sprint_pct: Optional[int],
    predictability: Optional[int],
    risk_count: int,
) -> str:
    parts = []
    if sprint_name and sprint_pct is not None:
        parts.append(f"{sprint_name} at {sprint_pct}% completion.")
    parts.append(f"Project is {overall_pct}% complete overall and tracking {status_label.lower()}.")
    if predictability is not None and predictability >= 85:
        parts.append("Team is delivering on commitments with strong predictability.")
    elif predictability is not None and predictability < 60:
        parts.append("Predictability is low — scope re-calibration recommended.")
    if risk_count > 0:
        parts.append(f"{risk_count} active risk(s) flagged this week.")
    return " ".join(parts)

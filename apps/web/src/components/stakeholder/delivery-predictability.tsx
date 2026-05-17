"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Target,
  Loader2,
  CheckCircle2,
  XCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  Gauge,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { ChartWrapper, chartColors } from "@/components/dashboard/chart-wrapper";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import { useSelectedProject } from "@/lib/project/context";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

/* ──────────────────────────────────────────────────────────────────────────
 * Stakeholder dashboard: Delivery Predictability
 *
 * Renders the v2 composite predictability score (see
 * apps/api/app/services/predictability_engine.py for the formula) together
 * with every piece of evidence the stakeholder needs to trust or question
 * the number:
 *
 *   1. Big overall score + RAG colour + one-line narrative
 *   2. Three component cards (Commitment Accuracy / Goal Hit Rate / Stability)
 *   3. Per-sprint audit cards - one per recent sprint showing planned,
 *      delivered, ratio, accuracy, whether the sprint hit its goal, and
 *      the recency weight applied
 *   4. Accuracy-trend line chart (symmetric accuracy, not raw ratio)
 *
 * Deliberately DOES NOT use a tooltip on the score - the product decision
 * was that this whole section is the tooltip. Every data point is on screen.
 * ────────────────────────────────────────────────────────────────────────── */

interface SprintAudit {
  sprintId: string;
  sprintName: string;
  endDate: string | null;
  plannedSp: number;
  completedSp: number;
  ratio: number;       // uncapped, e.g. 1.25 means team delivered 25% more than planned
  accuracy: number;    // 0-100
  hitGoal: boolean;    // ratio within ±15%
  weight: number;      // recency weight actually applied (0..1)
}

interface PredictabilityV2 {
  score: number | null;
  breakdown: {
    commitmentAccuracy: number | null;
    sprintGoalHitRate: number | null;
    stability: number | null;
  };
  sprints: SprintAudit[];
  reasonHidden: string | null;
  narrative: string | null;
  /* Hotfix 13 - cap explanation. When applied=true, ``capped_at`` is the
   * displayed score and ``raw`` is what the un-capped weighted math
   * gave. We surface the gap so stakeholders understand why their
   * components don't sum to the headline number. */
  cap?: {
    applied: boolean;
    raw: number | null;
    cappedAt: number | null;
    reason: string | null;
  };
  /* Velocity trend across the audit window (recent half vs older half). */
  velocityTrend?: {
    direction: "up" | "flat" | "down" | null;
    deltaPct: number | null;
    currentAvgSp: number | null;
    priorAvgSp: number | null;
  };
  /* Absolute output - useful when the team's commitment is small but
   * accurate (perfect 5 SP delivery isn't the same as perfect 50 SP). */
  throughput?: {
    avgCompletedSp: number | null;
    totalCompletedSp: number | null;
    sprintCount: number;
  };
}

function scoreColor(score: number | null): string {
  if (score === null) return "text-[var(--text-tertiary)]";
  if (score >= 85) return "text-[var(--color-rag-green)]";
  if (score >= 60) return "text-[var(--color-rag-amber)]";
  return "text-[var(--color-rag-red)]";
}

function scoreBg(score: number | null): string {
  if (score === null) return "bg-[var(--bg-surface-raised)]";
  if (score >= 85) return "bg-[var(--color-rag-green)]/10";
  if (score >= 60) return "bg-[var(--color-rag-amber)]/10";
  return "bg-[var(--color-rag-red)]/10";
}

function formatRatio(r: number): string {
  if (!Number.isFinite(r)) return "-";
  return r.toFixed(2);
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

// ── Component score card ────────────────────────────────────────────────

function ComponentCard({
  label,
  value,
  description,
  weight,
}: {
  label: string;
  value: number | null;
  description: string;
  /** Hotfix 13 - relative weight of this component in the composite
   * score, surfaced so stakeholders can see how the headline number is
   * built up. Numeric (0-100). */
  weight?: number;
}) {
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          {label}
        </p>
        {weight !== undefined && (
          <span className="shrink-0 rounded-full bg-[var(--bg-surface)] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            {weight}% weight
          </span>
        )}
      </div>
      <p className={cn("mt-2 text-3xl font-bold tabular-nums", scoreColor(value))}>
        {value === null ? "-" : `${value}%`}
      </p>
      <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-secondary)]">
        {description}
      </p>
    </div>
  );
}

// ── Velocity trend card (Hotfix 13) ───────────────────────────────────

function VelocityTrendCard({
  trend,
}: {
  trend: PredictabilityV2["velocityTrend"];
}) {
  const direction = trend?.direction;
  const Icon =
    direction === "up" ? TrendingUp : direction === "down" ? TrendingDown : Minus;
  const colorClass =
    direction === "up"
      ? "text-[var(--color-rag-green)]"
      : direction === "down"
        ? "text-[var(--color-rag-red)]"
        : "text-[var(--text-secondary)]";
  const headline =
    direction === "up"
      ? "Improving"
      : direction === "down"
        ? "Declining"
        : direction === "flat"
          ? "Stable"
          : "Not enough data";
  const deltaText =
    trend?.deltaPct === null || trend?.deltaPct === undefined
      ? null
      : `${trend.deltaPct >= 0 ? "+" : ""}${trend.deltaPct}%`;
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          Velocity Trend
        </p>
        <span className="shrink-0 rounded-full bg-[var(--bg-surface)] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
          context
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <Icon className={cn("h-6 w-6", colorClass)} />
        <span className={cn("text-2xl font-bold", colorClass)}>{headline}</span>
        {deltaText && (
          <span className={cn("text-sm font-semibold tabular-nums", colorClass)}>
            {deltaText}
          </span>
        )}
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-secondary)]">
        Compares the recent half of completed sprints to the older half.
        {trend?.currentAvgSp !== null && trend?.priorAvgSp !== null && trend ? (
          <>
            {" "}Current avg{" "}
            <span className="font-semibold text-[var(--text-primary)] tabular-nums">
              {trend.currentAvgSp} SP
            </span>
            {" vs prior avg "}
            <span className="font-semibold text-[var(--text-primary)] tabular-nums">
              {trend.priorAvgSp} SP
            </span>
            .
          </>
        ) : null}
      </p>
    </div>
  );
}

// ── Throughput card (Hotfix 13) ───────────────────────────────────────

function ThroughputCard({
  throughput,
}: {
  throughput: PredictabilityV2["throughput"];
}) {
  const avg = throughput?.avgCompletedSp ?? null;
  const total = throughput?.totalCompletedSp ?? null;
  const n = throughput?.sprintCount ?? 0;
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          Throughput
        </p>
        <span className="shrink-0 rounded-full bg-[var(--bg-surface)] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
          context
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <Gauge className="h-6 w-6 text-[var(--color-brand-secondary)]" />
        <span className="text-2xl font-bold tabular-nums text-[var(--text-primary)]">
          {avg === null ? "-" : avg}
        </span>
        <span className="text-sm font-semibold text-[var(--text-secondary)]">
          SP / sprint
        </span>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-secondary)]">
        Absolute output averaged across the last {n} completed sprint
        {n === 1 ? "" : "s"}.
        {total !== null && (
          <>
            {" Total delivered: "}
            <span className="font-semibold text-[var(--text-primary)] tabular-nums">
              {total} SP
            </span>
            .
          </>
        )}
      </p>
    </div>
  );
}

// ── Sprint audit card ──────────────────────────────────────────────────

function SprintAuditCard({ s, isMostRecent }: { s: SprintAudit; isMostRecent: boolean }) {
  const overshoot = s.ratio > 1.15;
  const undershoot = s.ratio < 0.85;
  const diffPct = Math.round((s.ratio - 1) * 100);
  const diffLabel =
    diffPct === 0 ? "Exactly on plan"
    : diffPct > 0 ? `Delivered ${diffPct}% more than planned`
    : `Delivered ${Math.abs(diffPct)}% less than planned`;

  return (
    <div
      className={cn(
        "rounded-lg border bg-[var(--bg-surface-raised)] p-3",
        s.hitGoal
          ? "border-[var(--color-rag-green)]/30"
          : overshoot
            ? "border-[var(--color-rag-amber)]/30"
            : "border-[var(--color-rag-red)]/30"
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[var(--text-primary)] truncate">
            {s.sprintName}
          </p>
          <p className="text-[11px] text-[var(--text-secondary)]">
            {formatDate(s.endDate)}
            {isMostRecent && " · most recent"}
            {s.weight > 0 && (
              <span className="ml-1 text-[var(--text-tertiary)]">
                · weight {Math.round(s.weight * 100)}%
              </span>
            )}
          </p>
        </div>
        {s.hitGoal ? (
          <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)] shrink-0" />
        ) : (
          <XCircle
            className={cn(
              "h-4 w-4 shrink-0",
              overshoot ? "text-[var(--color-rag-amber)]" : "text-[var(--color-rag-red)]"
            )}
          />
        )}
      </div>

      {/* Planned vs delivered row */}
      <div className="flex items-baseline gap-4 mb-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            Planned
          </p>
          <p className="text-base font-bold text-[var(--text-primary)] tabular-nums">
            {s.plannedSp} <span className="text-xs font-medium text-[var(--text-secondary)]">SP</span>
          </p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            Delivered
          </p>
          <p className="text-base font-bold text-[var(--text-primary)] tabular-nums">
            {s.completedSp} <span className="text-xs font-medium text-[var(--text-secondary)]">SP</span>
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            Ratio
          </p>
          <p
            className={cn(
              "text-base font-bold tabular-nums",
              s.hitGoal
                ? "text-[var(--color-rag-green)]"
                : overshoot
                  ? "text-[var(--color-rag-amber)]"
                  : "text-[var(--color-rag-red)]"
            )}
          >
            {formatRatio(s.ratio)}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between text-[11px]">
        <span className="text-[var(--text-secondary)]">{diffLabel}</span>
        <span className={cn("font-semibold", scoreColor(s.accuracy))}>
          Accuracy {s.accuracy}%
        </span>
      </div>
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────

export function DeliveryPredictability() {
  const [data, setData] = useState<PredictabilityV2 | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "sprint_plan_updated"]);
  const { selectedProject } = useSelectedProject();
  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    setLoading(true);
    const q = projectId ? `?projectId=${projectId}` : "";
    try {
      const res = await cachedFetch(`/api/analytics${q}`);
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const json = res.data as any;
        const v2 = json?.predictability?.v2;
        if (v2) {
          setData(v2 as PredictabilityV2);
        } else {
          setData(null);
        }
      } else {
        setData(null);
      }
    } catch {
      setData(null);
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Delivery Predictability" icon={Target}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  // Empty / insufficient-data state
  if (!data || data.score === null) {
    return (
      <DashboardPanel title="Delivery Predictability" icon={Target}>
        <div className="flex flex-col items-center justify-center py-10 gap-3 text-center">
          <Target size={28} className="text-[var(--text-tertiary)]" />
          <p className="text-sm font-semibold text-[var(--text-primary)]">
            Not enough sprint history yet
          </p>
          <p className="text-xs text-[var(--text-secondary)] max-w-md">
            {data?.narrative ||
              "Delivery predictability needs at least one completed sprint with committed work. Once a sprint closes, this card will show how close your team lands to what it commits to."}
          </p>
        </div>
      </DashboardPanel>
    );
  }

  // Chart payload - accuracy trend across sprints. We reverse so the chart
  // reads left-to-right as time progresses (DB returns most-recent-first).
  const chartRows = [...data.sprints]
    .reverse()
    .map((s) => ({ sprint: s.sprintName, accuracy: s.accuracy }));

  // Hotfix 13.2 - simplified delivery trend. One bar per completed
  // sprint showing the absolute SP delivered. Stakeholders read it as
  // "tall bar = good sprint, short bar = bad sprint", and the
  // chronological order makes the past-vs-present comparison obvious
  // without any artificial series split or reference line. Works
  // identically with 1 sprint (single bar) or 5 (a five-bar trend).
  const deliveryTrendRows = [...data.sprints]
    .reverse()
    .map((s) => ({
      sprint: s.sprintName,
      delivered: s.completedSp,
    }));

  return (
    <DashboardPanel title="Delivery Predictability" icon={Target}>
      {/* Big overall score + narrative */}
      <div className="mb-6 flex flex-col items-center text-center">
        <div
          className={cn(
            "flex h-24 w-24 items-center justify-center rounded-2xl",
            scoreBg(data.score)
          )}
        >
          <span className={cn("text-5xl font-bold tabular-nums", scoreColor(data.score))}>
            {data.score}
          </span>
        </div>
        <span className="mt-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          Predictability Score
        </span>
        {/* Hotfix 13 - when a cap is applied (small sample or realism
            ceiling), explain the gap between the components-weighted
            math and the displayed score so it doesn't look broken. */}
        {data.cap?.applied && data.cap.raw !== null && (
          <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-3 py-1 text-[11px] text-[var(--text-secondary)]">
            <Info className="h-3 w-3" />
            <span>
              Components weighted to{" "}
              <span className="font-semibold text-[var(--text-primary)] tabular-nums">
                {data.cap.raw}
              </span>
              {" → capped at "}
              <span className="font-semibold text-[var(--text-primary)] tabular-nums">
                {data.cap.cappedAt}
              </span>
              {data.cap.reason ? `. ${data.cap.reason}` : ""}
            </span>
          </div>
        )}
        {data.narrative && (
          <p className="mt-3 max-w-2xl text-sm text-[var(--text-primary)] leading-relaxed">
            {data.narrative}
          </p>
        )}
      </div>

      {/* Three components - these drive the predictability composite
          (weights 65 / 25 / 10). Each card shows its weight so the
          stakeholder can see how the headline score is built up. */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
        <ComponentCard
          label="Commitment Accuracy"
          value={data.breakdown.commitmentAccuracy}
          weight={65}
          description="How close each sprint landed to its planned story points. Over-delivery is penalised equally to under-delivery - both signal inaccurate planning."
        />
        <ComponentCard
          label="Sprint Goal Hit Rate"
          value={data.breakdown.sprintGoalHitRate}
          weight={25}
          description={"Share of recent sprints that finished within \u00b115% of the committed scope. Stakeholder\u2019s \u201ccan we trust the date\u201d metric."}
        />
        <ComponentCard
          label="Stability"
          value={data.breakdown.stability}
          weight={10}
          description="How consistent the delivery is across sprints. A team reliably at 70% scores higher here than one that swings 40% ↔ 130%."
        />
      </div>

      {/* Hotfix 13 - additional context metrics. These DON'T feed the
          composite score (so they don't double-count) but give two
          extra dimensions of trust: are we trending the right way,
          and is the absolute output meaningful? */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
        <VelocityTrendCard trend={data.velocityTrend} />
        <ThroughputCard throughput={data.throughput} />
      </div>

      {/* Per-sprint audit cards */}
      <div>
        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          Sprint-by-sprint breakdown
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {data.sprints.map((s, idx) => (
            <SprintAuditCard key={s.sprintId} s={s} isMostRecent={idx === 0} />
          ))}
        </div>
      </div>

      {/* Hotfix 13.2 - simplified delivery trend. One bar per sprint
          showing absolute delivered SP. Works for 1 sprint or 10 with
          no extra cleverness; chronological order makes "past vs
          present" obvious without artificial split lines. */}
      {deliveryTrendRows.length >= 1 && (
        <div className="mt-6">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Delivered SP per sprint
          </h4>
          <ChartWrapper height={200}>
            <BarChart data={deliveryTrendRows}>
              <CartesianGrid strokeDasharray="3 3" stroke={chartColors.border} vertical={false} />
              <XAxis
                dataKey="sprint"
                tick={{ fill: chartColors.text.secondary, fontSize: 11 }}
                axisLine={{ stroke: chartColors.border }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: chartColors.text.secondary, fontSize: 11 }}
                axisLine={{ stroke: chartColors.border }}
                tickLine={false}
                width={36}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-surface-raised)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "0.75rem",
                  color: "var(--text-primary)",
                  fontSize: 12,
                }}
                formatter={(v: unknown) => `${v} SP`}
              />
              <Bar
                dataKey="delivered"
                name="Delivered SP"
                fill={chartColors.brand.secondary}
                radius={[4, 4, 0, 0]}
                maxBarSize={64}
              />
            </BarChart>
          </ChartWrapper>
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-secondary)]">
            Each bar is one completed sprint, oldest on the left. Compare
            bar heights to see how delivery is trending.
          </p>
        </div>
      )}

      {/* Accuracy trend chart (only when 2+ sprints so the line is meaningful) */}
      {chartRows.length >= 2 && (
        <div className="mt-6">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Accuracy trend
          </h4>
          <ChartWrapper height={180}>
            <LineChart data={chartRows}>
              <CartesianGrid strokeDasharray="3 3" stroke={chartColors.border} vertical={false} />
              <XAxis
                dataKey="sprint"
                tick={{ fill: chartColors.text.secondary, fontSize: 11 }}
                axisLine={{ stroke: chartColors.border }}
                tickLine={false}
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fill: chartColors.text.secondary, fontSize: 11 }}
                axisLine={{ stroke: chartColors.border }}
                tickLine={false}
                width={32}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-surface-raised)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "0.75rem",
                  color: "var(--text-primary)",
                  fontSize: 12,
                }}
              />
              {/* 85% = green-zone threshold */}
              <ReferenceLine
                y={85}
                stroke={chartColors.rag.green}
                strokeDasharray="4 4"
                strokeOpacity={0.5}
              />
              <Line
                type="monotone"
                dataKey="accuracy"
                stroke={chartColors.brand.secondary}
                strokeWidth={2}
                dot={{ r: 4, fill: chartColors.brand.secondary }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ChartWrapper>
        </div>
      )}
    </DashboardPanel>
  );
}

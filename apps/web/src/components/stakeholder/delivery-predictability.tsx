"use client";

import { useState, useEffect, useCallback } from "react";
import { Target, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { ChartWrapper, chartColors } from "@/components/dashboard/chart-wrapper";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

interface PredictabilityData {
  overall: number;
  forecastAccuracy: number;
  sprintGoalAttainment: number;
  carryForwardRate: number;
  trend: { sprint: string; score: number }[];
}

function scoreColor(score: number, invertLogic = false): string {
  if (invertLogic) {
    if (score <= 15) return "text-[var(--color-rag-green)]";
    if (score <= 25) return "text-[var(--color-rag-amber)]";
    return "text-[var(--color-rag-red)]";
  }
  if (score >= 80) return "text-[var(--color-rag-green)]";
  if (score >= 60) return "text-[var(--color-rag-amber)]";
  return "text-[var(--color-rag-red)]";
}

function scoreBg(score: number, invertLogic = false): string {
  if (invertLogic) {
    if (score <= 15) return "bg-[var(--color-rag-green)]/10";
    if (score <= 25) return "bg-[var(--color-rag-amber)]/10";
    return "bg-[var(--color-rag-red)]/10";
  }
  if (score >= 80) return "bg-[var(--color-rag-green)]/10";
  if (score >= 60) return "bg-[var(--color-rag-amber)]/10";
  return "bg-[var(--color-rag-red)]/10";
}

interface ComponentRowProps {
  label: string;
  score: number;
  invertLogic?: boolean;
}

function ComponentRow({ label, score, invertLogic = false }: ComponentRowProps) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-[var(--bg-surface-raised)] px-4 py-3">
      <span className="text-sm text-[var(--text-secondary)]">{label}</span>
      <span className={cn("text-lg font-bold tabular-nums", scoreColor(score, invertLogic))}>
        {score}
      </span>
    </div>
  );
}

export function DeliveryPredictability() {
  const [data, setData] = useState<PredictabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete"]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await cachedFetch("/api/analytics");
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const json = res.data as any;
        const pred = json.predictability;
        if (pred) {
          // Build trend from velocity data if available
          const velocityTrend = json.velocity?.trend ?? [];
          const trend = velocityTrend.map((v: { sprint: string; planned: number; completed: number }) => ({
            sprint: v.sprint,
            score: v.planned > 0 ? Math.round((v.completed / v.planned) * 100) : 0,
          }));
          setData({
            overall: pred.overall ?? 0,
            forecastAccuracy: pred.estimateAccuracy ?? pred.forecastAccuracy ?? 0,
            sprintGoalAttainment: pred.sprintGoalAttainment ?? 0,
            carryForwardRate: pred.carryForwardRate ?? 0,
            trend,
          });
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
  }, []);

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

  if (!data) {
    return (
      <DashboardPanel title="Delivery Predictability" icon={Target}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <Target size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No predictability data available</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Complete sprint cycles to see delivery predictability metrics.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel title="Delivery Predictability" icon={Target}>
      {/* Large overall score */}
      <div className="mb-6 flex flex-col items-center">
        <div className={cn("flex h-20 w-20 items-center justify-center rounded-2xl", scoreBg(data.overall))}>
          <span className={cn("text-4xl font-bold tabular-nums", scoreColor(data.overall))}>
            {data.overall}
          </span>
        </div>
        <span className="mt-2 text-sm font-medium text-[var(--text-secondary)]">
          Predictability Score
        </span>
      </div>

      {/* Component breakdown */}
      <div className="space-y-2 mb-6">
        <ComponentRow label="Forecast Accuracy" score={data.forecastAccuracy} />
        <ComponentRow label="Sprint Goal Attainment" score={data.sprintGoalAttainment} />
        <ComponentRow label="Carry-Forward Rate" score={data.carryForwardRate} invertLogic />
      </div>

      {/* Trend chart */}
      {data.trend.length > 0 && (
        <div>
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Score Trend
          </h4>
          <ChartWrapper height={200}>
            <LineChart data={data.trend}>
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
              <Line
                type="monotone"
                dataKey="score"
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

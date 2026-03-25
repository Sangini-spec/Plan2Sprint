"use client";

import { useState, useEffect, useCallback } from "react";
import { TrendingUp, Loader2 } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { ChartWrapper, chartColors } from "@/components/dashboard/chart-wrapper";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface VelocityData {
  sprint: string;
  planned: number;
  completed: number;
}

export function MyVelocityTrend() {
  const { selectedProject } = useSelectedProject();
  const [chartData, setChartData] = useState<VelocityData[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "sprint_completed"]);

  const projectId = selectedProject?.internalId;

  const fetchVelocity = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const res = await cachedFetch(`/api/analytics${q}`);
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        const trend: VelocityData[] = data.velocity?.trend ?? [];
        setChartData(trend);
      } else {
        setChartData([]);
      }
    } catch {
      setChartData([]);
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => { fetchVelocity(); }, [fetchVelocity, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Velocity Trend" icon={TrendingUp}>
        <div className="flex items-center justify-center py-12">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (chartData.length === 0) {
    return (
      <DashboardPanel title="Velocity Trend" icon={TrendingUp}>
        <div className="flex flex-col items-center justify-center py-12 gap-2">
          <TrendingUp size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No velocity data available</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Velocity trends will appear after completing sprints.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel title="Velocity Trend" icon={TrendingUp}>
      <ChartWrapper height={250}>
        <BarChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={chartColors.border}
            vertical={false}
          />
          <XAxis
            dataKey="sprint"
            tick={{ fontSize: 11, fill: chartColors.text.secondary }}
            axisLine={{ stroke: chartColors.border }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: chartColors.text.secondary }}
            axisLine={false}
            tickLine={false}
            label={{
              value: "Story Points",
              angle: -90,
              position: "insideLeft",
              offset: 20,
              style: { fontSize: 11, fill: chartColors.text.secondary },
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--bg-surface-raised)",
              border: "1px solid var(--border-subtle)",
              borderRadius: 12,
              fontSize: 12,
              color: "var(--text-primary)",
            }}
            labelStyle={{ fontWeight: 600, marginBottom: 4 }}
          />
          <Legend
            wrapperStyle={{ fontSize: 12 }}
            iconType="circle"
            iconSize={8}
          />
          <Bar
            dataKey="planned"
            name="Planned"
            fill={chartColors.text.secondary}
            fillOpacity={0.3}
            radius={[4, 4, 0, 0]}
          />
          <Bar
            dataKey="completed"
            name="Completed"
            fill={chartColors.brand.secondary}
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ChartWrapper>
    </DashboardPanel>
  );
}

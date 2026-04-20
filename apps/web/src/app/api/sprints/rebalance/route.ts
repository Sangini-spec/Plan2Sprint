import { NextRequest, NextResponse } from "next/server";

// Extended timeout for AI-powered rebalancing (3 minutes)
export const maxDuration = 180;
export const dynamic = "force-dynamic";

const API_URL =
  process.env.API_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    // Forward auth headers
    const auth = req.headers.get("authorization");
    const cookie = req.headers.get("cookie");
    if (auth) headers["Authorization"] = auth;
    if (cookie) headers["Cookie"] = cookie;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 170000); // 170s

    const res = await fetch(`${API_URL}/api/sprints/rebalance`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    clearTimeout(timeout);
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error("[rebalance route] Error:", error);
    return NextResponse.json(
      { detail: "Rebalancing request timed out or failed" },
      { status: 504 }
    );
  }
}

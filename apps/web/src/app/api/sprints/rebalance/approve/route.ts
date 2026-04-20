import { NextRequest, NextResponse } from "next/server";

export const maxDuration = 60;

const API_URL =
  process.env.API_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    const auth = req.headers.get("authorization");
    const cookie = req.headers.get("cookie");
    if (auth) headers["Authorization"] = auth;
    if (cookie) headers["Cookie"] = cookie;

    const res = await fetch(`${API_URL}/api/sprints/rebalance/approve`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(55000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    return NextResponse.json(
      { detail: "Approval request failed" },
      { status: 504 }
    );
  }
}

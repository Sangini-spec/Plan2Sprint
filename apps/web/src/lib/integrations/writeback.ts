/**
 * Write-back safety enforcement.
 * Only specific fields are allowed to be written back to external tools.
 * This is a critical security boundary per the MRD.
 */

// Frozen allowlists — cannot be modified at runtime
export const JIRA_WRITEBACK_ALLOWLIST = Object.freeze([
  "assignee",
  "sprint_id",
  "story_points",
] as const);

export const ADO_WRITEBACK_ALLOWLIST = Object.freeze([
  "System.AssignedTo",
  "System.IterationPath",
  "Microsoft.VSTS.Scheduling.StoryPoints",
] as const);

// GitHub is read-only — no write-back allowed
export const GITHUB_WRITEBACK_ALLOWLIST = Object.freeze([] as const);

export type JiraWritebackField = (typeof JIRA_WRITEBACK_ALLOWLIST)[number];
export type AdoWritebackField = (typeof ADO_WRITEBACK_ALLOWLIST)[number];

/**
 * Validate that all fields in a write-back request are allowed.
 * Returns the list of disallowed fields (empty if all valid).
 */
export function validateWritebackFields(
  tool: "jira" | "ado" | "github",
  fields: Record<string, unknown>
): { valid: boolean; disallowedFields: string[] } {
  if (tool === "github") {
    return {
      valid: false,
      disallowedFields: Object.keys(fields),
    };
  }

  const allowlist = tool === "jira" ? JIRA_WRITEBACK_ALLOWLIST : ADO_WRITEBACK_ALLOWLIST;
  const disallowed = Object.keys(fields).filter(
    (f) => !(allowlist as readonly string[]).includes(f)
  );

  return {
    valid: disallowed.length === 0,
    disallowedFields: disallowed,
  };
}

/**
 * Build an audit-safe write-back payload with before/after states.
 */
export function buildWritebackPayload(
  tool: "jira" | "ado",
  itemId: string,
  fields: Record<string, unknown>,
  previousValues: Record<string, unknown>
): {
  tool: string;
  itemId: string;
  changes: { field: string; from: unknown; to: unknown }[];
} {
  return {
    tool,
    itemId,
    changes: Object.entries(fields).map(([field, value]) => ({
      field,
      from: previousValues[field] ?? null,
      to: value,
    })),
  };
}

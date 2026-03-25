/**
 * Write-back configuration.
 *
 * Sprint plan sync now uses comment-only mode — AI recommendations are posted
 * as comments to each work item in Jira/ADO. No fields are modified.
 *
 * Board status write-back (drag-and-drop column changes) still updates
 * the status field directly via the board writeback endpoint.
 */

// GitHub remains read-only — no write-back of any kind
export const GITHUB_WRITEBACK_ALLOWLIST = Object.freeze([] as const);

/**
 * Sprint plan writeback mode.
 * "comment" = post AI recommendation comments only (no field changes).
 */
export const WRITEBACK_MODE = "comment" as const;

export type WritebackMode = typeof WRITEBACK_MODE;

// Board status writeback still allows state field changes
const BOARD_WRITEBACK_FIELDS: Record<string, readonly string[]> = {
  jira: ["status"],
  ado: ["System.State"],
};

/**
 * Validate that all fields in a write-back request are allowed.
 * With comment-only sprint sync, only board status fields are valid for direct write-back.
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

  const allowlist = BOARD_WRITEBACK_FIELDS[tool] || [];
  const disallowed = Object.keys(fields).filter(
    (f) => !allowlist.includes(f)
  );

  return {
    valid: disallowed.length === 0,
    disallowedFields: disallowed,
  };
}

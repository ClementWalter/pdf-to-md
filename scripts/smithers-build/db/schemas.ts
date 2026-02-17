// db/schemas.ts — Zod schemas for all workflow step outputs
//
// Rules:
// - Use .nullable() NEVER .optional() (OpenAI structured outputs rejects optional)
// - Smithers auto-adds runId, nodeId, iteration columns
// - Every schema validates agent JSON output before SQLite persistence

import { z } from "zod";

// ─────────────────────────────────────────────────────────────
// Shared sub-schemas
// ─────────────────────────────────────────────────────────────

const issueSchema = z.object({
  severity: z.enum(["critical", "major", "minor"]),
  description: z.string(),
  file: z.string().nullable(),
  line: z.number().nullable(),
  suggestion: z.string().nullable(),
});

export type Issue = z.infer<typeof issueSchema>;

// ─────────────────────────────────────────────────────────────
// Implement Step
// ─────────────────────────────────────────────────────────────

export const ImplementSchema = z.object({
  /** Files created in this iteration */
  filesCreated: z.array(z.string()),
  /** Files modified in this iteration */
  filesModified: z.array(z.string()),
  /** Git commit messages made */
  commitMessages: z.array(z.string()),
  /** What was accomplished in this iteration */
  whatWasDone: z.string(),
  /** The next smallest atomic unit to implement */
  nextSmallestUnit: z.string().nullable(),
  /** Whether the implementer believes the full project is complete */
  believesComplete: z.boolean(),
});

export type ImplementOutput = z.infer<typeof ImplementSchema>;

// ─────────────────────────────────────────────────────────────
// Test Step
// ─────────────────────────────────────────────────────────────

export const TestSchema = z.object({
  /** Whether all tests passed */
  testsPassed: z.boolean(),
  /** Number of tests passing */
  testsPassCount: z.number(),
  /** Number of tests failing */
  testsFailCount: z.number(),
  /** Summary of failing tests (names + error messages) */
  failingSummary: z.string().nullable(),
  /** Raw pytest output (truncated if too long) */
  testOutput: z.string(),
});

export type TestOutput = z.infer<typeof TestSchema>;

// ─────────────────────────────────────────────────────────────
// Review Step
// ─────────────────────────────────────────────────────────────

export const ReviewSchema = z.object({
  /** Whether the code is approved */
  approved: z.boolean(),
  /** Overall severity of findings */
  severity: z.enum(["critical", "major", "minor", "none"]),
  /** Issues found during review */
  issues: z.array(issueSchema),
  /** Overall feedback for the implementer */
  feedback: z.string(),
});

export type ReviewOutput = z.infer<typeof ReviewSchema>;

// ─────────────────────────────────────────────────────────────
// Final Review Step (readyToMoveOn gating)
// ─────────────────────────────────────────────────────────────

export const FinalReviewSchema = z.object({
  /** THE GATE FLAG — is the project complete and ready to ship? */
  readyToMoveOn: z.boolean(),
  /** Reasoning for the decision — fed back to next pass's Implement step */
  reasoning: z.string(),
  /** Overall approval */
  approved: z.boolean(),
  /** Quality score 1-10 */
  qualityScore: z.number().min(1).max(10),
  /** Remaining issues preventing approval */
  remainingIssues: z.array(
    z.object({
      severity: z.enum(["critical", "major", "minor"]),
      description: z.string(),
      file: z.string().nullable(),
    }),
  ),
});

export type FinalReviewOutput = z.infer<typeof FinalReviewSchema>;

// ─────────────────────────────────────────────────────────────
// Pass Tracker (records which pass just completed)
// ─────────────────────────────────────────────────────────────

export const PassTrackerSchema = z.object({
  totalIterations: z.number(),
  summary: z.string(),
});

export type PassTrackerOutput = z.infer<typeof PassTrackerSchema>;

// ─────────────────────────────────────────────────────────────
// Schema registry — maps table names to schemas
// ─────────────────────────────────────────────────────────────

export const outputSchemas = {
  implement: ImplementSchema,
  test_results: TestSchema,
  review: ReviewSchema,
  final_review: FinalReviewSchema,
  pass_tracker: PassTrackerSchema,
};

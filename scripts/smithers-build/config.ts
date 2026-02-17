// config.ts — Workflow constants and model configuration
//
// Single Ralph loop for pdf2md — no multi-phase gating needed

import { resolve } from "path";

/** Maximum number of implement→test→review→final-review passes */
export const MAX_PASSES = 5;

/** Absolute path to the pdf-to-md repository root */
export const REPO_ROOT = resolve(import.meta.dir, "../..");

/** Model assignments per agent role */
export const MODELS = {
  implementer: "gpt-5.3-codex",
  reviewer: "claude-opus-4-6",
  finalReviewer: "claude-opus-4-6",
} as const;

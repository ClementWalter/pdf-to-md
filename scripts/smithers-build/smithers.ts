// smithers.ts — Smithers orchestrator setup with schema registry
//
// Creates SQLite database for state persistence and auto-generated tables from Zod schemas.
// Exports JSX primitives for workflow composition.

import {
  createSmithers,
  Sequence,
  Parallel,
  Ralph,
  Branch,
} from "smithers-orchestrator";
import { outputSchemas } from "./db/schemas.js";

const DB_PATH = "./smithers.db";

const api = createSmithers(outputSchemas, {
  dbPath: DB_PATH,
});

export const { Workflow, Task, useCtx, smithers, tables, db } = api;

// Re-export JSX primitives for components to import from one place
export { Sequence, Parallel, Ralph, Branch };

// agents.ts — Agent configurations for pdf2md build workflow
//
// Three agent roles: implementer (Codex), reviewer (Claude), final reviewer (Claude)

import { ClaudeCodeAgent } from "smithers-orchestrator";
import { MODELS, REPO_ROOT } from "./config.js";

// ─────────────────────────────────────────────────────────────
// Shared system prompt sections
// ─────────────────────────────────────────────────────────────

const PROJECT_CONTEXT = `
## PROJECT CONTEXT

You are building **pdf2md** — a web service that converts any publicly-accessible PDF to markdown
via a simple URL rewrite. Given a PDF at \`https://site.com/path/file.pdf\`, navigating to
\`{DOMAIN}/site.com/path/file.pdf\` returns the markdown.

**Stack:**
- Python 3.11+ with **FastAPI** + Uvicorn
- **Marker** (\`marker-pdf\`) for PDF→Markdown conversion
- Local filesystem cache (SHA-256 of URL as key)
- Docker deployment on Scaleway

**PRD:** \`PRD.md\` in the repository root — the full specification for everything we're building.

**Project structure (target):**
\`\`\`
pdf-to-md/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── PRD.md
├── src/
│   └── pdf2md/
│       ├── __init__.py
│       ├── main.py          # FastAPI app, routes
│       ├── converter.py     # Marker wrapper, PDF→MD logic
│       ├── cache.py         # Cache read/write (disk)
│       ├── downloader.py    # PDF fetching with validation
│       └── config.py        # Settings via pydantic-settings
├── tests/
│   ├── test_converter.py
│   ├── test_cache.py
│   ├── test_downloader.py
│   └── test_routes.py
└── .github/
    └── workflows/
        └── deploy.yml
\`\`\`
`;

const PYTHON_RULES = `
## PYTHON RULES

- Use \`uv\` as the package manager — run commands with \`uv run\`
- Use PEP 723 inline script metadata for standalone scripts
- Use \`pyproject.toml\` for project configuration (NOT setup.py or setup.cfg)
- Use pydantic-settings for configuration management
- Use proper logging (\`import logging\`) — NEVER use print statements
- Add module-level docstrings to every Python file
- Always explain the "why" in comments, not the "what"
- Use pytest for testing with fixtures and parametrize
- One test = one assertion (no looping over fixture data)
- Run tests with \`uv run pytest\` — always check for previous failures first
`;

const GIT_RULES = `
## GIT RULES

- Atomic commits — one logical change per commit
- Format: "type(scope): description"
  - feat(routes): add PDF conversion endpoint
  - feat(cache): implement SHA-256 based disk cache
  - test(downloader): add URL validation tests
  - fix(converter): handle corrupted PDF gracefully
- After committing: git pull --rebase origin main && git push
- NEVER create branches — work on current branch
- NEVER commit .db files, __pycache__, or .pyc files
`;

const WORKSPACE_POLICY = `
## WORKSPACE POLICY

Uncommitted changes in the worktree are expected and normal.
Do NOT refuse to work because of dirty git state. Proceed with implementation regardless.
Other agents in this workflow may have made changes that are not yet committed.
`;

const JSON_OUTPUT = `
CRITICAL OUTPUT REQUIREMENT:
When you have completed your work, you MUST end your response with a JSON object
wrapped in a code fence. The JSON format is specified in your task prompt.
Do NOT output natural language after the JSON block.
`;

// ─────────────────────────────────────────────────────────────
// Agent factories
// ─────────────────────────────────────────────────────────────

function buildSystemPrompt(role: string): string {
  return [
    `# Role: ${role}`,
    PROJECT_CONTEXT,
    PYTHON_RULES,
    GIT_RULES,
    WORKSPACE_POLICY,
    JSON_OUTPUT,
  ].join("\n\n");
}

/** Codex agent with full write access for implementing Python code */
export function makeImplementer() {
  return new ClaudeCodeAgent({
    model: MODELS.implementer,
    systemPrompt: buildSystemPrompt(
      "Implementer — Write Python code, FastAPI routes, tests, and configuration",
    ),
    yolo: true,
    cwd: REPO_ROOT,
    timeoutMs: 3600000, // 60 min
  });
}

/** Claude agent for code review (read-only) */
export function makeReviewer() {
  return new ClaudeCodeAgent({
    model: MODELS.reviewer,
    systemPrompt: buildSystemPrompt(
      "Reviewer — Check code quality, PRD compliance, test coverage, and Python best practices",
    ),
    permissionMode: "default",
    cwd: REPO_ROOT,
    timeoutMs: 1800000, // 30 min
  });
}

/** Claude agent for final gating decision (read-only) */
export function makeFinalReviewer() {
  return new ClaudeCodeAgent({
    model: MODELS.finalReviewer,
    systemPrompt: buildSystemPrompt(
      "Final Reviewer — Decide if the project is complete and ready to ship",
    ),
    permissionMode: "default",
    cwd: REPO_ROOT,
    timeoutMs: 1800000, // 30 min
  });
}

#!/usr/bin/env bash
# run.sh — Launch the pdf2md Smithers build workflow
#
# Clears previous state and starts fresh.
# Do NOT run this unless you want to rebuild from scratch.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════╗"
echo "║  pdf2md — Smithers Build Workflow                ║"
echo "║  Loop: Implement → Test → Review → Final Review  ║"
echo "║  Max passes: ${MAX_PASSES:-5}                              ║"
echo "╚══════════════════════════════════════════════════╝"

# Clean previous run state
rm -f smithers.db*

bunx smithers run workflow.tsx

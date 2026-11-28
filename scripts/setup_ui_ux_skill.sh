#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v node >/dev/null 2>&1 || { echo "Node.js is required to install UI/UX Pro Max." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required to install UI/UX Pro Max." >&2; exit 1; }
npm exec --yes --package=ui-ux-pro-max-cli@2.15.0 -- uipro init --ai universal --force
echo
echo "UI/UX Pro Max installed under .agents/skills/ui-ux-pro-max/"
echo "Review the generated files, then commit them if you want the full skill versioned with Planline."

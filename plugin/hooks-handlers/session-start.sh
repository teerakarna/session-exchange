#!/usr/bin/env bash
# Resolve the environment root, seed this session's claim, inject what the root has to say.
#
# Deliberately not `set -e`: a hook must never fail a session start, so every path out of here
# exits 0. The Python side catches its own exceptions and reports them as context for the same
# reason.
set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if ! command -v python3 >/dev/null 2>&1; then
  # Plain stdout is added to the session's context on SessionStart, which is the only reason this
  # can be said at all. Saying nothing would leave a machine where the plugin is installed and
  # silently inert, and indistinguishable from one where nothing needed doing.
  echo "[session-exchange] python3 is not on PATH, so presence, claims and handoffs are not being read."
  exit 0
fi

python3 "${ROOT}/lib/hook.py" SessionStart || exit 0

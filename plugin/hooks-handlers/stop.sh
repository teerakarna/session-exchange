#!/usr/bin/env bash
# Report a handoff that arrived since this session was last shown the set. Silent otherwise.
#
# Unlike the other two handlers this one has nothing to say about a missing python3. It fires after
# every turn, and whatever a Stop hook prints makes Claude continue, so a notice here would be one
# more forced turn each time, which is the loop #123 is about.
set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

command -v python3 >/dev/null 2>&1 || exit 0

python3 "${ROOT}/lib/hook.py" Stop || exit 0

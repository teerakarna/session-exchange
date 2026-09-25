#!/usr/bin/env bash
# Clear this session's claim, so nobody has to remember to.
#
# Silent on success. Nothing reads injected context at session end, so the only reason this reports
# a failure at all is that a claim outliving its session shows up to every other session as a live
# peer working somewhere it is not.
set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

command -v python3 >/dev/null 2>&1 || exit 0

python3 "${ROOT}/lib/hook.py" SessionEnd || exit 0

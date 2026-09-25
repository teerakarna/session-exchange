"""The hook entrypoint. One function, dispatched on the event that fired.

What each event is for:

- **SessionStart** - resolve the root, seed this session's claim, and inject whatever the root has to
  say. Fires on startup, resume, clear and compact, so it has to be safe to run repeatedly against
  state it may already have written.
- **SessionEnd** - clear the claim. This is what makes "set your row to idle when you are done" stop
  depending on a session remembering to, which it reliably did not.

`Stop` is deliberately not wired yet. Its job in the design is catching handoffs posted mid-session,
and until handoff matching exists it could only spawn a process per turn to do nothing. It goes in
with the matcher that gives it something to read.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import claims
import exchange_root
import hookio
import legacy
import registry
import store


def session_start(data, root, lines):
    session_id = data.get("session_id")
    # The payload has no display name, so it comes from the registry - looked up by the id the
    # payload does carry, rather than by walking the process tree, which is the same answer for the
    # price of one directory read.
    known = registry.by_session_id(session_id) or {}
    _, problem = claims.seed(root, session_id, data.get("cwd") or os.getcwd(),
                             name=known.get("name"))
    if problem:
        lines.append(hookio.problem(problem))

    _, config_problem = store.config(root)
    if config_problem:
        lines.append(hookio.problem(config_problem))

    # Presence and handoff rendering land next. Until then the only thing worth injecting is the
    # migration guard, which is the one that must not wait: a half-migrated machine looks identical
    # to a finished one at the output, and this line is the only thing that distinguishes them.
    state = legacy.report(root)
    if state["double_fire"]:
        wired = sorted({name for _, name in state["wired"]})
        lines.append(hookio.problem(
            f"{len(wired)} legacy hook script(s) still wired: {', '.join(wired)}. "
            "They fire alongside this plugin, so presence and handoffs are rendered twice. "
            "Run `exchange doctor` for where the wiring is."
        ))
    for problem in state["problems"]:
        lines.append(hookio.problem(problem))


def session_end(data, root, lines):
    problem = claims.clear(root, data.get("session_id"))
    if problem:
        # Worth saying even though nobody may read it: a claim that outlives its session shows up as
        # a live peer to everyone else, which is the wrong-and-not-visibly-wrong state again.
        lines.append(hookio.problem(problem))


HANDLERS = {
    "SessionStart": session_start,
    "SessionEnd": session_end,
}


def main(default_event, argv=None):
    data = hookio.payload()
    event = hookio.event_name(data, default_event)
    lines = []

    try:
        resolution = exchange_root.resolve(data.get("cwd") or os.getcwd())
        if resolution.problem:
            lines.append(hookio.problem(resolution.problem))
        elif resolution.root is None:
            # Rule 3. No exchange in this environment, so there is nothing to do and nothing to say.
            return 0
        else:
            handler = HANDLERS.get(event)
            if handler is None:
                lines.append(hookio.problem(
                    f"wired under {event}, which this plugin does not handle. "
                    "Check hooks/hooks.json against how it was installed."
                ))
            else:
                handler(data, resolution.root, lines)
    except Exception as exc:  # noqa: BLE001 - a hook may not take a session down with it
        lines.append(hookio.problem(
            f"{type(exc).__name__} in the {event} hook: {exc}. "
            "Session unaffected; the exchange is not being updated."
        ))

    hookio.emit(event, lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "SessionStart"))

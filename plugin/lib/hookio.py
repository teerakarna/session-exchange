"""Talking to Claude Code from a hook.

Two rules, both learned the hard way by the scripts this replaces:

**Echo the event name back from the payload, never from the wiring.** The same handler can be wired
under more than one event, and if the `hookEventName` in the reply does not match the event that
fired, the context is dropped. Reading it from the payload means the wiring cannot drift out of sync
with what the reply claims to be. One lane's handoffs were invisible for exactly that reason.

**A hook must never fail a session start.** Anything that goes wrong becomes a line of injected
context and an exit status of 0. A traceback on stderr would be both louder and less useful, and a
non-zero exit is worse than the problem it reports.
"""

from __future__ import annotations

import json
import sys

PREFIX = "session-exchange"


def payload(stream=None):
    """The hook payload, or `{}`.

    An unparseable payload is not worth reporting: there is nothing actionable in it and no way to
    reply, since the event name it would need is the thing that could not be read.
    """
    stream = sys.stdin if stream is None else stream
    try:
        if stream.isatty():
            return {}
    except (AttributeError, ValueError):
        pass
    try:
        return json.loads(stream.read() or "{}") or {}
    except (ValueError, OSError):
        return {}


def event_name(data, default):
    name = data.get("hook_event_name")
    return name if isinstance(name, str) and name else default


def emit(event, lines, out=None):
    """Inject context, or print nothing at all.

    Silence is a real answer and the common one: no root here, or a root with nothing to say. An
    empty section header injected every session would train the reader to skip the section.
    """
    lines = [line for line in lines if line]
    if not lines:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": "\n".join(lines),
                }
            }
        ),
        file=sys.stdout if out is None else out,
    )


def problem(text):
    """A problem, marked so its source is obvious in a wall of injected context."""
    return f"[{PREFIX}] {text}"

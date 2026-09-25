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

    `{}` rather than whatever `json.loads` returned, because valid JSON need not be an object. A
    payload of `5` or `[1]` parses fine and then every caller's `.get` raises an AttributeError from
    outside the one try block `hook.main` has, which exits non-zero with a traceback. That is the
    guarantee this module calls absolute, broken by two characters.

    `isinstance` rather than `or {}`, which was the first attempt and covered only the falsy half:
    `null`, `0` and `[]` came back as `{}` while `5`, `true`, `"x"` and `[1]` went straight through
    and exited 1. A fix that handles the one case somebody thought to test is worse than no fix,
    because the test then reads as cover for the rest.

    `except Exception` on the read rather than a list of types, because that list was wrong three
    passes running. It began as `ValueError, OSError`; it gained `AttributeError` when `sys.stdin`
    turned out to be `None` whenever fd 0 is not open; then a stream whose `read` answers `None`
    raised `TypeError`, and a deeply nested array raised `RecursionError`, which is a `RuntimeError`
    and so outside all of it. Every one of those exited 1 with a traceback out of `main`. The list
    was never the rule. The rule is that this function has one answer for everything that goes
    wrong, because `hook.main` calls it outside its only try block and the first line of this module
    promises that a hook never fails a session start. `BaseException` still propagates, so a Ctrl-C
    is still a Ctrl-C.

    The `isatty` guard above stays enumerated, because each of its arms has an input that shows it -
    a wrapper around a pipe has no `isatty`, a closed stream raises `ValueError` - and widening it
    would turn a narrowing into a mutation nothing could catch.
    """
    stream = sys.stdin if stream is None else stream
    try:
        if stream.isatty():
            return {}
    except (AttributeError, ValueError):
        pass
    try:
        # No `or "{}"` guard on the read. Empty input raises ValueError here and is caught below, so
        # a guard for it would be a rule no input could distinguish from its absence.
        data = json.loads(stream.read())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def event_name(data, default):
    name = data.get("hook_event_name")
    return name if isinstance(name, str) and name else default


def emit(event, lines, out=None):
    """Inject context, or print nothing at all.

    Silence is a real answer and the common one: no root here, or a root with nothing to say. An
    empty section header injected every session would train the reader to skip the section.

    The falsy filter is a contract, not a live rule, and is labelled as such because this repo
    deletes rules nothing can reach. Every line the one caller appends comes from `problem()`, which
    always returns a non-empty string, so today the filter removes nothing and `if not lines` does
    all the work. It is kept because the caller set grows by design - presence rendering and the
    write path both land later, and a renderer with nothing to say returning `""` is the ordinary
    way to write one. That would inject the empty section this function exists to prevent, so the
    filter is here first and its test hand-feeds an input no caller can currently produce.

    Where the guarantee at the top of this module stops: a *reader* that has closed the read end of
    stdout. The process then exits 120 with a `BrokenPipeError` on stderr, and not from this
    `print`, which returns fine - the bytes sit in the buffer and CPython's shutdown flush is what
    fails, after `main` has already returned 0. Wrapping the print changes nothing and neither does
    flushing inside the wrapper. Issue #14 rather than a fix here, since nothing has shown that
    Claude Code closes a hook's stdout early and the only fix that works is redirecting fd 1 to
    devnull after a failed flush. So the guarantee is absolute for any input, not for any reader.
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

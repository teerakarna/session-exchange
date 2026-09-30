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
import os
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
    deletes rules nothing can reach. Every line the one caller appends is a `problem()` or a
    presence row, neither of which is ever empty, so today the filter removes nothing and
    `if not lines` does all the work. It is kept because the caller set grows by design - handoff
    rendering lands next, and a renderer with nothing to say returning `""` is the ordinary way to
    write one. That would inject the empty section this function exists to prevent, so the
    filter is here first and its test hand-feeds an input no caller can currently produce.

    The guarantee at the top of this module used to stop at the *reader*. Three states of it, all
    reached by a real session and all previously a traceback on stderr:

    - A pipe whose read end is closed, block-buffered, which is the ordinary one. The `print`
      returns fine; the bytes sit in the buffer and CPython's shutdown flush is what fails, long
      after `main` returned 0 and outside anything that can catch it.
    - The same pipe with `PYTHONUNBUFFERED` set, or a reply past the buffer's size, where the write
      happens during the `print` and raises there instead.
    - fd 1 not open at all, where CPython puts `None` in `sys.stdout` - the exact mirror of the
      `sys.stdin` case `payload` handles, and it arrives here as `None.flush()`.

    So the write and the flush are both inside the `try`, and a stdout that is `None` returns early.
    The guarantee is absolute for any reader as well as for any input.
    """
    lines = [line for line in lines if line]
    if not lines:
        return
    stream = sys.stdout if out is None else out
    # `print(file=None)` is a documented no-op rather than an error, so without this the failure is
    # the `flush` below and it is an AttributeError, which is neither what the caller is guarding
    # against nor something `main` can catch - `emit` is called outside its only try block. There is
    # nothing to write to and no fd to redirect, so returning is the whole of the answer.
    if stream is None:
        return
    reply = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": "\n".join(lines),
            }
        }
    )
    try:
        print(reply, file=stream)
        stream.flush()
    except OSError:
        # The flush is explicit rather than left to the interpreter, and it is inside the same `try`
        # as the write because either one can be where the pipe breaks: buffered, the `print`
        # returns and the flush raises; unbuffered, the `print` raises and the flush never runs.
        #
        # And do not shorten the body to `pass`. That was tried and it still exits 120: a failed
        # write leaves the data in the buffer, so the interpreter's own shutdown flush retries it
        # and fails again, on the way out, where nothing can catch it. Pointing fd 1 at devnull is
        # what makes that retry succeed - the buffer still holds fd 1, and `dup2` changes what fd 1
        # is, so the bytes land in the dark instead of on a pipe with no reader.
        #
        # Only for the real stdout, and `sys.__stdout__` is what says that. `sys.stdout` means
        # whatever it points at right now, which under a caller that has swapped it for an in-memory
        # stream is exactly the guess this guard exists to avoid - `test_hook.py` does that swap.
        # `out=` is a test seam too, and a stream that failed to write would not be fixed by
        # touching fd 1. `sys.__stdout__` is also `None` when fd 1 is not open, which the early
        # return above has already handled.
        #
        # `OSError` stays narrow, for the reason the `isatty` guard above stays enumerated: every
        # reader state that reaches a handler is either this or the `None` above. A stream whose
        # write raises anything else is the `out=` seam, where the caller is the test.
        if stream is sys.__stdout__:
            null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(null, 1)
            os.close(null)


def problem(text):
    """A problem, marked so its source is obvious in a wall of injected context."""
    return f"[{PREFIX}] {text}"

"""Read Claude Code's own session registry.

`~/.claude/sessions/*.json`, one file per live session, named for the process id and carrying
`sessionId`, `cwd`, `name` and a per-turn `status`. This already exists and is already maintained,
so presence is rendered from it rather than from anything this plugin asks a session to keep up to
date.
Nobody edits a presence row again.

Two things it cannot tell you, which is why claims exist alongside it:

- `status` is per-turn. `idle` there means "not currently in a turn", not "finished with the work".
- It knows where a session is, never what it is doing.

Liveness is checked rather than trusted. A registry file can outlive its process, and a row that
reads as current and is not is worse than no row.

Not every row is a peer either, which is #31 and is a question about what a row *means* rather than
about how one is drawn. Measured against this machine: eight rows where the session list showed six
sessions, the two extras both `kind: bg` and both belonging to a background job spawned by one of
the six. One of them carried the same `name` as the interactive row that spawned it and a different
`sessionId`, so presence would have shown two identical rows and a reader keyed on the name could
not have told them apart. A background job is not somebody to coordinate with - it is a session
doing its own work, and it cannot answer. So `entries` means peers, `by_session_id` means any row
at all, and which of the two a caller wants is never a default it gets by accident.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

SESSIONS_DIR = pathlib.Path.home() / ".claude" / "sessions"

# The kinds that are not a person. Live values seen in `kind`: `interactive` and `bg`.
NOT_PEERS = ("bg",)


def is_peer(row):
    """Is this row somebody to coordinate with, rather than a session's own background job?

    A blocklist rather than `kind == "interactive"`, which is the direction this repo always takes
    when it has to choose which way to be wrong. An allowlist drops every kind Claude Code invents
    next, silently, and a session that is present and unrendered is this project's founding
    failure; a blocklist renders one row too many, which a reader can see and report. The rows with
    no `kind` at all - the version that predates the field - come out as peers either way, and that
    is the case that would otherwise render nobody present on that version at all.

    One function because the rule has to hold in both places that ask, `entries` filtering a list
    and `hook` deciding whether to seed a claim, and two copies of it are two things that drift
    with only one of them under test. See #31.
    """
    return row.get("kind") not in NOT_PEERS


def alive(pid):
    """Is this pid a live process? Signal 0 rather than `ps`, so it costs nothing."""
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def entries(sessions_dir=SESSIONS_DIR, live_only=True, peers_only=True):
    """Registry rows that are peers, sorted by name. Unreadable files are skipped, not guessed at.

    The pid is taken from inside the file rather than from its name: the two agree today, and
    depending on a filename to carry data is how the rest of this mess started.

    `peers_only=False` means every row, which is what an identity lookup wants and what a presence
    render must not have. Between the two, filtering is the default: a caller that forgets to say
    gets the conservative answer, and the row this drops is the one that reads as a second person.
    """
    sessions_dir = pathlib.Path(sessions_dir)
    rows = []
    if not sessions_dir.is_dir():
        return rows
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or not row.get("sessionId"):
            continue
        if peers_only and not is_peer(row):
            continue
        if live_only and not alive(row.get("pid")):
            continue
        rows.append(row)
    return sorted(rows, key=lambda r: str(r.get("name") or r.get("sessionId")))


def by_session_id(session_id, sessions_dir=SESSIONS_DIR, rows=None):
    """The registry row for a known session id, or None.

    What a hook uses, because the payload already carries the id and an exact lookup costs one
    directory read. Walking the process tree is only for a command that does not know who it is.

    Every kind, unlike `entries`. This answers "what is this row", and the caller that most needs it
    is the one deciding whether the id it was handed is a peer at all - a filter here would answer
    None for a background job and be indistinguishable from an id the registry has never heard of,
    which are two different situations with two different right responses.

    `rows` is every row already read, for a caller that needs them for something else as well.
    """
    if not session_id:
        return None
    if rows is None:
        rows = entries(sessions_dir, live_only=False, peers_only=False)
    for row in rows:
        if row.get("sessionId") == session_id:
            return row
    return None


def _parents(pid, limit=12, run=subprocess.run):
    """This process and its ancestors, nearest first.

    `ps` rather than `/proc`, because macOS has no `/proc` and this is the one place the plugin has
    to care which kernel it is on. Bounded, so a cycle or a lie cannot hang a command.

    `run` is a seam, not a feature. Nothing overrides it in the plugin, and the two ways the call
    below fails for real - no `ps` on PATH in a minimal image, and a `ps` that hangs past the
    timeout - are not reachable from a test on a machine that has a working one. Without the seam
    the `except` was unfalsifiable: deleting it left the suite green, which is the state this repo
    treats as a defect rather than as coverage.
    """
    chain = []
    current = int(pid)
    for _ in range(limit):
        if current <= 1:
            break
        chain.append(current)
        try:
            # The argv is fixed and the only interpolation is an integer pid, so there is no
            # untrusted input to shell out. `ps` is left unqualified on purpose: it is /bin/ps on
            # macOS and /usr/bin/ps on most Linux, and hardcoding either breaks the other for no
            # gain. Ruff's S603/S607 are answered in ruff.toml rather than inline, because an
            # inline suppression binds to a physical line and the formatter decides which line
            # this call ends up on.
            out = run(
                ["ps", "-o", "ppid=", "-p", str(current)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            break
        parent = out.stdout.strip()
        if not parent.isdigit():
            break
        current = int(parent)
    return chain


def own_entry(sessions_dir=SESSIONS_DIR, peers_only=True):
    """The registry row for the session this process is running inside, or None.

    Found by walking up the process tree until a pid matches a registry row, which is the only way a
    command run through a tool call can learn its own session id: it is not in the environment, and
    matching on cwd would pick the wrong session the moment two of them work in the same directory.

    Peers only, which is `entries`'s default and is load-bearing here rather than incidental.
    Inside a background job the chain holds **two** registry pids - the job's own and the
    interactive session that spawned it - and nearest-first would answer with the job. Everything
    this is for then writes under an id `entries` no longer renders: a claim that cannot be read
    back, and a handoff from a sender nobody can find. Skipping to the interactive ancestor
    attributes the work to the session a human can actually reach, which is the same call #31 makes
    about what a row means.

    `peers_only=False` is the other question: which row is nearest, background or not. `claim` asks
    it, because a claim is about this process rather than about who to attribute it to. See #68.
    """
    rows = {
        int(r["pid"]): r
        for r in entries(sessions_dir, live_only=False, peers_only=peers_only)
        if str(r.get("pid", "")).isdigit()
    }
    for pid in _parents(os.getpid()):
        if pid in rows:
            return rows[pid]
    return None

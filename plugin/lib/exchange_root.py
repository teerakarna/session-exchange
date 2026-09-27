"""Decide which environment root, if any, this session belongs to.

The only place in the plugin where a path is decided. Everything else is handed a root and does
not look for one, which is what makes the same plugin usable from several workspaces without any
of them seeing another's state.

Precedence, highest first:

1. `CC_EXCHANGE_ROOT`. A per-pane override that needs no config and no marker file - the point of
   it is to work in a directory that has not been marked.
2. The nearest ancestor of the session's cwd containing `.claude/exchange.json`. Nearest, so with
   nested roots the innermost wins; that falls out of walking up and stopping at the first hit.
3. Nothing. A silent no-op, and no auto-creation anywhere. This is the documented expectation
   already: if no exchange context is injected, this environment has no exchange and there is
   nothing to do.

Never read across roots, in either direction. `resolve` returns one root and callers do not walk
past it.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import NamedTuple

MARKER = pathlib.PurePath(".claude/exchange.json")
OVERRIDE_VAR = "CC_EXCHANGE_ROOT"


class Resolution(NamedTuple):
    """Which root, by which rule, and anything the caller should say out loud.

    `problem` is not an error to raise. A hook must never fail a session start, so a bad root
    resolves to no root and reports why. Silence is only correct when there is genuinely nothing
    configured, which is rule 3.
    """

    root: pathlib.Path | None
    rule: str
    problem: str | None = None

    @property
    def marker(self) -> pathlib.Path | None:
        return self.root / MARKER if self.root else None


def resolve(cwd, environ=None) -> Resolution:
    """Resolve the environment root for a session running in `cwd`."""
    environ = os.environ if environ is None else environ

    override = (environ.get(OVERRIDE_VAR) or "").strip()
    if override:
        path = pathlib.Path(override).expanduser()
        if not path.is_dir():
            # Loud, because someone set this deliberately and it silently did nothing. An
            # unset variable is rule 3; a set-and-wrong one is a mistake worth surfacing.
            return Resolution(
                None,
                "override-invalid",
                f"{OVERRIDE_VAR} is set to {override!r}, which is not a directory.",
            )
        return Resolution(path.resolve(), "override")

    start = pathlib.Path(cwd).expanduser()
    if not start.is_dir():
        return Resolution(None, "cwd-invalid", f"cwd {str(cwd)!r} is not a directory.")

    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / MARKER).is_file():
            return Resolution(candidate, "marker")

    return Resolution(None, "unmarked")


def read_marker(root):
    """The marker's contents, or a problem describing why they could not be read.

    Returns `(config, problem)`. A marker that exists but does not parse is the same shape of
    failure as a parser that matches nothing: it must not read as "no exchange here".
    """
    path = pathlib.Path(root) / MARKER
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"{path} does not exist."
    except ValueError as exc:
        return None, f"{path} is not valid JSON: {exc}."
    if not isinstance(config, dict):
        return None, f"{path} must hold a JSON object, not {type(config).__name__}."
    return config, None


def git_root(start):
    """The enclosing git working tree, by walking up for `.git`. No subprocess.

    `.git` is a directory in a normal clone and a file in a worktree or submodule, so test for
    existence rather than for a directory.
    """
    start = pathlib.Path(start).expanduser().resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def init_candidates(cwd):
    """Where `exchange init` would mark, and what else it could have.

    The default is the nearest directory holding a `CLAUDE.md`, *strictly above* the enclosing git
    root. Skipping the git root is deliberate: a repo-scoped exchange coordinates nothing, because
    the sessions that need to see each other are in sibling repos.

    Returns `(default, candidates)`. `default` may be None, in which case there is nothing
    sensible to mark and `init` should say so rather than pick something.
    """
    start = pathlib.Path(cwd).expanduser().resolve()
    repo = git_root(start)
    # Inside a repo, `parents` is strict and that is the whole point: never the git root itself, and
    # never a directory below it. With no enclosing repo there is no repo-scoped exchange to stop,
    # so `cwd` is looked at like any ancestor - and that is the case that matters, because launching
    # from the area directory is the documented way to start a session and it was the one place the
    # default came back empty. Nothing else is loosened: cwd still has to carry a `CLAUDE.md`, still
    # has to not be home, and still has to survive `is_merge_point`.
    searched = [start, *start.parents] if repo is None else list(repo.parents)

    home = pathlib.Path.home().resolve()
    candidates = [d for d in searched if (d / "CLAUDE.md").is_file() and d != home]
    default = next((d for d in candidates if not is_merge_point(d)), None)
    return default, candidates


def is_merge_point(path):
    """Would marking here merge two workspace areas that are meant to stay separate?

    Derived rather than hardcoded, because a hardcoded path is the bug class this plugin exists to
    remove. The tell: look at the immediate children that carry their own `CLAUDE.md`, and ask
    whether they are repositories or areas. Children that are git roots make this a directory of
    repos, which is a legitimate root - sibling repos are exactly the sessions that need to see each
    other. Children that are *not* git roots but still carry a `CLAUDE.md` make this a directory of
    areas, and marking it would give a session in one area sight of another's presence and handoffs.
    That is the one thing root resolution exists to prevent.
    """
    path = pathlib.Path(path)
    if (path / ".git").exists():
        # A git root is one workspace by definition, so its subdirectories are its own contents and
        # not sibling areas. Without this, a repo that *stores* `CLAUDE.md` files rather than being
        # described by one reads as a directory of areas and `init` refuses inside it: a dotfiles
        # repo holding managed copies, a docs or template repo, a monorepo with a file per package
        # and no nested `.git`. `.exists()` rather than `.is_dir()` because a worktree and a
        # submodule spell `.git` as a file, and both worktrees this plugin was built in are that
        # kind. Nothing that used to be caught stops being caught: a child that is a repo was
        # already excluded by the filter below.
        return False
    try:
        children = [p for p in path.iterdir() if p.is_dir()]
    except OSError:
        return False
    areas = [c for c in children if (c / "CLAUDE.md").is_file() and not (c / ".git").exists()]
    return len(areas) >= 2

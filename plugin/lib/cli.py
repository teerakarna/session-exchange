"""`exchange` - the write path and the diagnostics, at the terminal.

Writes stay at the terminal rather than behind a tool the model can call, which is where the same
decision landed on the last tool built here. Reads are pushed by hooks, because a read surface that
has to be asked would reintroduce the exact failure this replaces: nobody thought to look.

Exit codes: 0 fine, 1 something is wrong, 2 not built yet. The third is not the second - a command
that does not exist must not report success, and it must not look like a fault either.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import claims
import exchange_root
import legacy
import registry
import store
import validate

NOT_BUILT = 2


def _resolved(args):
    """The root, or a printed explanation and None."""
    resolution = exchange_root.resolve(args.cwd)
    if resolution.problem:
        print(f"problem: {resolution.problem}")
        return None
    if resolution.root is None:
        default, candidates = exchange_root.init_candidates(args.cwd)
        print("No environment root for this directory, so there is nothing to show.")
        if default:
            print(f"`exchange init` would mark {default}.")
        elif candidates:
            print("Nothing here is a sensible root; pass one explicitly to `exchange init`.")
        return None
    return resolution


def cmd_init(args):
    if args.path:
        target = pathlib.Path(args.path).expanduser().resolve()
        if not target.is_dir():
            print(f"problem: {target} is not a directory")
            return 1
    else:
        target, candidates = exchange_root.init_candidates(args.cwd)
        if target is None:
            print("Nothing above here looks like an environment root.")
            if candidates:
                print("Refused as a root, because marking one would merge separate workspaces:")
                for candidate in candidates:
                    print(f"  {candidate}")
            print("Pass a directory explicitly if you are sure.")
            return 1
        print(f"Default: {target}")
        for candidate in candidates:
            if candidate != target:
                note = (
                    " (refused: marking it would merge separate workspaces)"
                    if exchange_root.is_merge_point(candidate)
                    else ""
                )
                print(f"Also possible: {candidate}{note}")

    if exchange_root.is_merge_point(target) and not args.force:
        print(
            f"Refusing to mark {target}: its subdirectories are separate workspaces, and one "
            "exchange across them would show each the others' sessions and handoffs. "
            "Mark them individually, or pass --force if this really is one workspace."
        )
        return 1

    marker = target / ".claude" / "exchange.json"
    if marker.is_file():
        config, problem = store.config(target)
        print(f"Already marked: {marker}")
        if problem:
            print(f"problem: {problem}")
            return 1
        print(f"  name: {config['name']}")
        return 0

    problem = store.write_json(
        marker, {"name": args.name or target.name}, validate.load("exchange")
    )
    if problem:
        print(f"problem: {problem}")
        return 1
    store.sessions_dir(target).mkdir(parents=True, exist_ok=True)
    store.handoffs_dir(target).mkdir(parents=True, exist_ok=True)
    print(f"Marked {marker}")
    print(
        "Sessions started under here will now seed a claim. Nothing else changes until the "
        "plugin is installed."
    )
    return 0


def cmd_show(args):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    root = resolution.root
    config, problem = store.config(root)
    print(f"root      {root}  (by {resolution.rule})")
    print(f"name      {config['name']}")
    if problem:
        print(f"problem   {problem}")

    own = registry.own_entry()
    if own:
        print(f"this      {own.get('name')}  {own.get('sessionId')}")

    live = {row.get("sessionId") for row in registry.entries()}
    held, problems = claims.load_all(root)
    print(f"claims    {len(held)}")
    for claim in held:
        mark = " " if claim["session_id"] in live else "!"
        focus = claim.get("focus") or "(no focus stated)"
        shown = focus[: config["max_focus_chars"]]
        print(f" {mark} {claim.get('name') or claim['session_id']}  {shown}")
        if claim.get("paths"):
            print(f"     paths: {', '.join(claim['paths'][: config['max_hot_paths']])}")
    if any(claim["session_id"] not in live for claim in held):
        print("  ! marks a claim whose session is no longer in the registry: stale, not current.")
    for problem in problems:
        print(f"problem   {problem}")

    handoffs, handoff_problems = store.read_all(store.handoffs_dir(root), validate.load("handoff"))
    open_count = sum(1 for h in handoffs if h.get("status") != "closed")
    print(f"handoffs  {len(handoffs)} stored, {open_count} not closed")
    for problem in handoff_problems:
        print(f"problem   {problem}")
    return 1 if problem or problems or handoff_problems else 0


def cmd_claim(args):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    session_id = args.session or (registry.own_entry() or {}).get("sessionId")
    if not session_id:
        print(
            "problem: could not work out which session this is. The registry has no entry for "
            "any process above this one. Pass --session explicitly."
        )
        return 1

    # The display name is looked up for the id being claimed as, not for this process. With
    # `--session` those are different, and borrowing the caller's name would label someone else's
    # claim with it and then show it to everyone as stale.
    known = registry.by_session_id(session_id) or {}
    if not claims.path(resolution.root, session_id).is_file():
        claims.seed(resolution.root, session_id, args.cwd, name=known.get("name"))

    claim, problem = claims.update(
        resolution.root,
        session_id,
        focus=args.focus,
        add={
            f: v
            for f, v in (("repos", args.repo), ("paths", args.path), ("tickets", args.ticket))
            if v
        },
        replace={"paths": args.set_path} if args.set_path else None,
        clear_fields=[
            f
            for f, on in (
                ("paths", args.clear_paths),
                ("repos", args.clear_repos),
                ("tickets", args.clear_tickets),
            )
            if on
        ],
    )
    if problem:
        print(f"problem: {problem}")
        return 1
    print(f"claimed as {claim.get('name') or claim['session_id']}")
    if claim.get("focus"):
        print(f"  focus: {claim['focus']}")
    for field in claims.LIST_FIELDS:
        if claim.get(field):
            print(f"  {field}: {', '.join(claim[field])}")
    return 0


# Each entry: the step number that delivers it, and how its evidence is read from live state.
# Never from a recorded claim of progress - a migration that reports where it thinks it got to is a
# migration that can be wrong about it, and the half-done state is the dangerous one.
def _steps(root):
    plugin = pathlib.Path(__file__).resolve().parents[1]
    handoffs, _ = store.read_all(store.handoffs_dir(root), validate.load("handoff"))
    state = legacy.report(root)
    return [
        (
            1,
            "parser fixed and failing loud in place",
            None,
            "needs the legacy renderer and the source ledger; asked for by `doctor` in the "
            "environment that has them, not from here",
        ),
        (2, "root resolution extracted", (plugin / "lib" / "exchange_root.py").is_file(), None),
        (
            3,
            "plugin skeleton, hooks manifest, schemas, command",
            (plugin / "hooks" / "hooks.json").is_file()
            and (plugin / "schemas" / "handoff.schema.json").is_file()
            and (plugin / "commands" / "exchange.md").is_file(),
            None,
        ),
        (
            4,
            "open handoffs imported out of the markdown ledger",
            any("imported" in h for h in handoffs) if handoffs else False,
            None,
        ),
        (5, "this root marked", (pathlib.Path(root) / ".claude" / "exchange.json").is_file(), None),
        (
            6,
            "every other root marked",
            None,
            "one root cannot see another, by design; run `doctor` there",
        ),
        (7, "legacy hooks unwired and deleted", not state["on_disk"] and not state["wired"], None),
    ]


def cmd_doctor(args):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    root = resolution.root
    faults = 0

    print(f"root      {root}  (by {resolution.rule})")
    config, problem = store.config(root)
    if problem:
        faults += 1
        print(f"problem   {problem}")
    else:
        print(f"marker    valid, name {config['name']!r}")

    state = legacy.report(root)
    print(
        f"legacy    {len(state['on_disk'])} script(s) on disk, "
        f"{len(state['wired'])} wiring(s) found"
    )
    for path in state["on_disk"]:
        print(f"          on disk: {path.name}")
    for settings, name in state["wired"]:
        print(f"          wired:   {name}  in {settings}")
    for problem in state["problems"]:
        faults += 1
        print(f"problem   {problem}")
    if state["double_fire"]:
        faults += 1
        print(
            "DOUBLE FIRE: legacy hooks are still wired and will render alongside this plugin. "
            "Until they are unwired, presence and handoffs appear twice and a stalled migration "
            "is indistinguishable from a finished one."
        )

    print("steps")
    first_incomplete = None
    for number, what, done, why_unknown in _steps(root):
        if done is None:
            mark = "?"
        elif done:
            mark = "x"
        else:
            mark = " "
            if first_incomplete is None:
                first_incomplete = number
        print(f"  [{mark}] {number}. {what}")
        if why_unknown:
            print(f"        not checkable here: {why_unknown}")
    print(
        "  [?] means this check is not implemented or not answerable from here. It is printed "
        "rather than skipped: a diagnostic that quietly omits a check reads exactly like one "
        "that passed it."
    )
    if first_incomplete:
        print(f"next      step {first_incomplete}")
    else:
        print("next      nothing outstanding that is checkable from here")
    return 1 if faults else 0


def cmd_not_built(args):
    print(
        f"`exchange {args.command}` is not built yet: it arrives with migration step "
        f"{args.step}. Nothing was changed."
    )
    return NOT_BUILT


def build_parser():
    parser = argparse.ArgumentParser(prog="exchange", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cwd",
        default=os.getcwd(),
        help="resolve the root from here instead of the working directory",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="mark a directory as an environment root")
    init.add_argument("path", nargs="?", help="default: the nearest area above the enclosing repo")
    init.add_argument("--name", help="display name; defaults to the directory name")
    init.add_argument(
        "--force",
        action="store_true",
        help="mark a directory whose subdirectories are separate workspaces",
    )
    init.set_defaults(func=cmd_init)

    show = sub.add_parser("show", help="who is here, what they claim, what is waiting")
    show.set_defaults(func=cmd_show)

    claim = sub.add_parser("claim", help="state what this session is working on")
    claim.add_argument("--focus", help="what you are doing, in a sentence")
    claim.add_argument("--repo", action="append", default=[], help="repeatable")
    claim.add_argument("--path", action="append", default=[], help="repeatable; adds")
    claim.add_argument("--set-path", action="append", default=[], help="repeatable; replaces")
    claim.add_argument("--ticket", action="append", default=[], help="repeatable")
    claim.add_argument("--clear-paths", action="store_true")
    claim.add_argument("--clear-repos", action="store_true")
    claim.add_argument("--clear-tickets", action="store_true")
    claim.add_argument("--session", help="override the session id, if detection fails")
    claim.set_defaults(func=cmd_claim)

    doctor = sub.add_parser("doctor", help="live state, with evidence, and what is outstanding")
    doctor.set_defaults(func=cmd_doctor)

    handoff = sub.add_parser("handoff", help="post or answer a handoff (not built yet)")
    handoff.set_defaults(func=cmd_not_built, step=4)

    migrate = sub.add_parser("migrate", help="run a migration step (not built yet)")
    migrate.set_defaults(func=cmd_not_built, step=4)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

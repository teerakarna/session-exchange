"""`exchange` - the write path and the diagnostics, at the terminal.

Writes stay at the terminal rather than behind a tool the model can call, which is where the same
decision landed on the last tool built here. Reads are pushed by hooks, because a read surface that
has to be asked would reintroduce the exact failure this replaces: nobody thought to look.

Exit codes: 0 fine, 1 something is wrong, 2 a usage error from argparse. Exit 2 used to mean "not
built yet" as well, and with every migration step built it means one thing again.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import claims
import decommission
import exchange_root
import handoffs
import legacy
import migrate
import registry
import store
import validate


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
            # Which directories were looked at is not the same in both branches, and the message has
            # to say the one that ran. Inside a repo the search starts strictly above it and cwd is
            # never considered, so "here" would send someone hunting in a directory the tool did not
            # look at; with no enclosing repo cwd does count, so "above" would do the reverse.
            repo = exchange_root.git_root(args.cwd)
            looked = f"above {repo}" if repo else "here or above"
            print(f"Nothing {looked} looks like an environment root.")
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
        if (target / ".git").exists():
            # #33: a repo that *stores* `CLAUDE.md` files rather than being described by one has
            # exactly the shape of a directory of areas, and from outside the two are identical.
            # Said here rather than decided in `is_merge_point`, because exempting git roots there
            # also exempted a git root holding two real areas, which is the one arrangement the
            # refusal exists for. A note costs a reader one line; the exemption was silent.
            print(
                "Note: it is also a git root, so those subdirectories may be its own stored "
                "contents rather than sibling workspaces - a repo holding managed copies of "
                "CLAUDE.md files looks the same from here. Nothing can tell the two apart "
                "automatically, so --force is the answer when you know it is one workspace."
            )
        return 1

    marker = store.marker_path(target)
    if marker.is_file():
        config, problem = store.config(target)
        print(f"Already marked: {marker}")
        if problem:
            print(f"problem: {problem}")
            return 1
        print(f"  name: {store.printable(config['name'])}")
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
    print(f"name      {store.printable(config['name'])}")
    if problem:
        print(f"problem   {problem}")

    own = registry.own_entry()
    if own:
        print(f"this      {own.get('name')}  {own.get('sessionId')}")

    # Every kind of row, not just peers: a background job that is running has not stopped, and the
    # hook's stale line sends people here to decide what to delete. Same live set `hook.presence`
    # counts against.
    live = {row.get("sessionId") for row in registry.entries(peers_only=False)}
    held, problems = claims.load_all(root)
    print(f"claims    {len(held)}")
    for claim in held:
        mark = " " if claim["session_id"] in live else "!"
        shown = claims.describe_focus(claim, config["max_focus_chars"])
        print(f" {mark} {claims.describe_name(claim)}  {shown}")
        # Every list field a claim can hold, not just paths. `claim --repo` and `--ticket` were
        # accepted, validated and written, and then no reader rendered them: a write that succeeds
        # and cannot be read back is indistinguishable from one that was dropped, and handoffs are
        # addressed to repo-and-path scope, so half the scope was invisible to the people it is for.
        for field, shown_list in claims.describe_scope(claim, config["max_hot_paths"]):
            print(f"     {field}: {shown_list}")
    if any(claim["session_id"] not in live for claim in held):
        print("  ! marks a claim whose session is no longer running: stale, not current.")
    for problem in problems:
        print(f"problem   {problem}")

    # `handoffs.load_all` rather than `store.read_all`, so an unreadable or contested status move is
    # reported here too. `show` is the command people actually run, and a check that only one reader
    # performs is a check most readers do not get.
    stored, handoff_problems = handoffs.load_all(root)
    open_count = sum(1 for _, status in stored if status != handoffs.CLOSED)
    print(f"handoffs  {len(stored)} stored, {open_count} not closed")
    for problem in handoff_problems:
        print(f"problem   {problem}")
    return 1 if problem or problems or handoff_problems else 0


def cmd_claim(args):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    # #68. `own_entry` skips a background job's own row and answers with the session that spawned
    # it, which is right for a handoff and wrong here: `claims.update` replaces `focus`, so a
    # subagent claiming anything would rewrite what the person said they were doing, under their
    # own id. Refused rather than written under the job's id, which the hook declines to seed for
    # the reason #31 gives and which nothing renders. `--session` is there for doing it on purpose.
    nearest = None if args.session else registry.own_entry(peers_only=False)
    if nearest and not registry.is_peer(nearest):
        spawner = registry.own_entry()
        if not spawner:
            print(
                "problem: this is a background job, and no session above it is in the registry, "
                "so there is no session to claim for. A claim says what a session is doing, so "
                "the session makes it."
            )
            return 1
        name = store.printable(str(spawner.get("name") or ""))
        spawner_id = store.printable(str(spawner.get("sessionId")))
        print(
            "problem: this is a background job, and a claim from it would be made as the session "
            f"that started it ({name or spawner_id}) and replace what that session says it is "
            "doing. A claim says what a session is doing, so the session makes it. "
            f"Pass --session {spawner_id} to claim as it on purpose."
        )
        return 1
    session_id = args.session or (nearest or {}).get("sessionId")
    if not session_id:
        print(
            "problem: could not work out which session this is. The registry has no entry for "
            "any process above this one. Pass --session explicitly."
        )
        return 1

    # The same guard the handoff side gets, on the other side of the comparison it exists for. #46
    # is about `to.repo` being matched against a claim's `repos`, and a containment rule on one
    # operand contains nothing: refusing `--repo /etc` on `handoff post` and accepting it on `claim`
    # hands the matcher the same absolute path by a different route. `--set-path` goes through it
    # too, because it writes the field that `--path` appends to.
    #
    # Here rather than in `claims.update`, which is where the sweep could reach it, for the reason
    # the #45 note below is here: the message names the flag the person typed, and `claims.update`
    # knows field names instead. That is only sound while this is the sole writer of these two
    # fields, which it is - `hook.py` seeds `session_id`, `cwd` and `name` and nothing else, so
    # there is no second route in. A second writer means moving this into `claims.update` and losing
    # the flag names, rather than adding a copy here, because two copies of a containment rule is
    # how one of them ends up being the older one. The checks in `test_cli.py` are what would notice
    # this being deleted.
    for flag, values in (
        ("--repo", args.repo),
        ("--path", args.path),
        ("--set-path", args.set_path),
    ):
        for value in values or ():
            fault = store.scope_fault(flag, value)
            if fault:
                print(f"problem: {fault}")
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
    for line in claims.describe_settings(claim):
        print(line)
    return 0


# Each entry: the step number that delivers it, and how its evidence is read from live state.
# Never from a recorded claim of progress - a migration that reports where it thinks it got to is a
# migration that can be wrong about it, and the half-done state is the dangerous one.
def _steps(root):
    plugin = pathlib.Path(__file__).resolve().parents[1]
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
        (4, "open handoffs imported out of the markdown ledger", *_step4(root)),
        (5, "this root marked", store.marker_path(root).is_file(), None),
        (
            6,
            "every other root marked",
            None,
            "one root cannot see another, by design; run `doctor` there",
        ),
        (7, "legacy hooks unwired and retired", not state["on_disk"] and not state["wired"], None),
    ]


# The fourth answer a step can give, beside done, outstanding and unknown: there is nothing to do
# here, and that is a finished answer. Not `None`, which is "not checkable from here" and is the
# wrong reading for a root that is perfectly checkable and simply never had a ledger (#38). Not
# `True` either, because "done" would claim an import happened. Excluded from `next` on purpose
# rather than by falling through a branch meant for something else.
NOT_APPLICABLE = "n/a"


def _step4(root):
    """`(done, why)` for the import. Three real states, which is why it has its own function.

    Whether a root ever had a markdown ledger cannot be derived: the plugin names no paths, so the
    marker has to say. Absent means none. `init` never writes it, so on a root that did have a
    ledger the owner has to add it, and the reason line says how, since this is the one answer that
    reads as finished when it may only be undeclared. Before this the evidence was pinned false on
    every root, so `doctor` pointed at step 4 forever and would have kept steps 5 to 7 unreachable
    once `migrate` gates on it.

    Done is derived from the same plan `migrate` prints, never from a record existing: an import
    that posted three of five reads as outstanding, and so does a closure in the ledger that has not
    reached the store yet. A ledger that cannot be read is unknown, since it may be gone on purpose
    or only moved.

    A missing or unreadable marker is unknown rather than not applicable. A missing one declares
    nothing, and `store.config` reads it as defaults with no problem. A broken one hands back
    defaults with the problem. Neither set of defaults has a `legacy_ledger`, so reading them as an
    answer would call a root finished because its marker was absent or broken.
    """
    if not store.marker_path(root).is_file():
        return None, "there is no marker yet, so whether this root had a ledger cannot be told"
    config, problem = store.config(root)
    if problem:
        return None, "the marker is unreadable, so whether this root had a ledger cannot be told"
    if "legacy_ledger" not in config:
        return NOT_APPLICABLE, (
            "no `legacy_ledger` in the marker, so there is nothing to import. If this root did keep"
            " a markdown ledger, name it there"
        )
    block = config["legacy_ledger"]
    path = migrate.ledger_path(root, block)
    try:
        path.read_bytes()
    except OSError as exc:
        return None, f"the ledger at {path} cannot be read: {type(exc).__name__}"
    prepared = migrate.prepare(root, block)
    if prepared.problems:
        return False, (
            f"{len(prepared.problems)} problem(s), listed by `exchange migrate --step 4`"
        )
    if prepared.stranded:
        return False, (
            f"{len(prepared.stranded)} imported handoff(s) open with no entry left in the ledger;"
            " close them, or restore the entry"
        )
    pending = migrate.outstanding(prepared)
    if pending:
        return False, f"{pending} write(s) waiting; `exchange migrate --step 4` shows them"
    return True, None


def _running():
    """What the plugin that is running says it is, and where it is running from.

    The host caches an install by the version declared in `plugin.json`, so a version that does not
    move is an update that never reaches the copy the hooks run, while the host reports it as the
    latest (#49). The cached copy has no `.git`, so the version and the path are all it can say
    about itself, and the path is what shows a cache directory rather than the clone.
    """
    plugin = pathlib.Path(__file__).resolve().parents[1]
    try:
        manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text("utf-8"))
        version = manifest["version"]
        # A `null` would print as `None`, which reads like an answer to "which copy is this".
        if not isinstance(version, str):
            raise TypeError(type(version).__name__)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        return f"plugin    version unreadable ({type(exc).__name__}), running from {plugin}"
    return f"plugin    {store.printable(version)}, running from {plugin}"


def cmd_doctor(args):
    # Before the root, because a stale install is worth knowing about whether or not there is one.
    print(_running())
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
    elif resolution.marker and resolution.marker.is_file():
        print(f"marker    valid, name {config['name']!r}")
    else:
        # `store.config` returns the schema defaults and no problem when the marker is absent,
        # which is right for a renderer and wrong to print as "valid". Reachable only by the
        # override, since the walk finds a root by finding the marker - and it contradicted step 5
        # two lines below, which is the kind of disagreement that teaches people to stop reading
        # the output.
        print(
            f"marker    absent, so name {config['name']!r} and every cap are defaults. "
            "This root came from the override rather than from a marker; step 5 writes one."
        )

    state = legacy.report(root)
    print(
        f"legacy    {len(state['on_disk'])} script(s) on disk, "
        f"{len(state['wired'])} wiring(s) found"
    )
    for path in state["on_disk"]:
        print(f"          on disk: {path.name}")
    for settings, name in state["wired"]:
        scope = "machine-wide" if (settings, name) in state["machine_wide"] else "this root"
        print(f"          wired:   {name}  in {settings}  ({scope})")
    for problem in state["problems"]:
        faults += 1
        print(f"problem   {problem}")
    if state["double_fire"]:
        faults += 1
        print(
            "DOUBLE FIRE: legacy hooks are still wired under this root and will render alongside "
            "this plugin. Until they are unwired, presence and handoffs appear twice and a stalled "
            "migration is indistinguishable from a finished one."
        )
    if state["machine_wide"]:
        faults += 1
        print(
            "CROSS ROOT: a legacy wiring in the user's own settings fires for every session on "
            "this machine, whatever root it belongs to, so it can inject another environment's "
            "presence here. Which root it renders cannot be read from here - run `doctor` there. "
            "Reported separately from DOUBLE FIRE because it is a different fault: not this "
            "root's rendering twice, but another root's rendering at all."
        )

    # The store itself, which `doctor` read and said nothing about: `_steps` calls `load_all` for
    # the step 4 evidence and dropped its problems on the floor, so the one command whose job is to
    # report what is wrong was the one place an unreadable record did not show up. Both record
    # types, for the reason the hook gives.
    #
    # The three below it are about files and directories rather than about records, so nothing that
    # walks records has ever had a reason to look at them. See #51 and #53. A pre-#44 record draws
    # two lines, the generic refusal and then the conversion, and that pair is deliberate: the
    # first is what every other reader shows, and the second is the only place that says there is a
    # way out.
    _, claim_problems = claims.load_all(root)
    _, record_problems = handoffs.load_all(root)
    store_problems = [
        *claim_problems,
        *record_problems,
        *handoffs.unconverted(root),
        *handoffs.unresolved(root),
        *handoffs.orphan_moves(root),
        *store.litter(root),
    ]
    print(f"store     {len(store_problems)} fault(s) in the records and the files under them")
    for problem in store_problems:
        faults += 1
        print(f"problem   {problem}")

    print("steps")
    first_incomplete = None
    for number, what, done, why in _steps(root):
        if done is None:
            mark = "?"
        elif done == NOT_APPLICABLE:
            mark = "-"
        elif done:
            mark = "x"
        else:
            mark = " "
            if first_incomplete is None:
                first_incomplete = number
        print(f"  [{mark}] {number}. {what}")
        if why:
            if done == NOT_APPLICABLE:
                label = "not applicable"
            elif done is None:
                label = "not checkable here"
            else:
                label = "outstanding"
            print(f"        {label}: {why}")
    print(
        "  [?] means this check is not implemented or not answerable from here. It is printed "
        "rather than skipped: a diagnostic that quietly omits a check reads exactly like one "
        "that passed it. [-] means there is nothing to do here, which is an answer, not a gap."
    )
    if first_incomplete:
        print(f"next      step {first_incomplete}")
    else:
        print("next      nothing outstanding that is checkable from here")
    return 1 if faults else 0


def _body(args):
    """The body text, or a printed complaint and None.

    `-` reads stdin, because a handoff body is markdown and the useful ones are several paragraphs
    with backticks in them. Passing that through a shell argument is a quoting exercise nobody
    completes correctly on the first try, and a body mangled in transit is a handoff that says
    something its sender did not.
    """
    if args.body != "-":
        return args.body
    text = sys.stdin.read()
    if not text.strip():
        print("problem: nothing arrived on stdin, so there is no body to post")
        return None
    return text


def cmd_handoff_post(args):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    to, problem = handoffs.to_scope(repo=args.repo, paths=args.path, session_id=args.session)
    if problem:
        print(f"problem: {problem}")
        return 1
    body = _body(args)
    if body is None:
        return 1

    own = registry.own_entry() or {}
    record, problem = handoffs.post(
        resolution.root,
        to,
        body,
        args.cwd,
        session_id=own.get("sessionId"),
        name=own.get("name"),
    )
    if problem:
        print(f"problem: {problem}")
        return 1
    # The width the readers will render this scope at, not a second number invented here. This one
    # line is the exception `DECLINED` describes - the scope is what the typist just typed, and they
    # are reading the reply - but it is the same call the list makes, so it takes the same cap.
    config, config_problem = store.config(resolution.root)
    print(f"posted {record['id']} to {handoffs.describe(record['to'], config['max_focus_chars'])}")
    if config_problem:
        # Says the handoff is on disk, because the exit code below is 1 and on its own it does not.
        # A caller reading the non-zero as "it did not post" retries, ids are random so the retry
        # writes a second record, and the root then holds two handoffs for one intent with nothing
        # anywhere comparing them.
        print(f"problem   the handoff is written; {config_problem}")
    if "session_id" in record["to"]:
        # #45. A note here rather than a refusal in `handoffs`, and rather than a guard in
        # `set_status`: addressing is a hint to a reader, not access control, so the only thing
        # actually wrong with a mistyped id is that nobody is coming. Said at the moment it is
        # typed, because that is the last moment anyone is looking - a handoff addressed to an id no
        # session has is otherwise permanently open, unreachable, and counted in `show`'s "N not
        # closed" forever, with nothing anywhere saying why.
        #
        # In `cli` deliberately, unlike the stripping in `handoffs.describe`. The argument in
        # `DECLINED` is that this module's output is wrong in front of the person who typed the
        # command, and here that is exactly true: they chose the id and they are reading the reply.
        target = record["to"]["session_id"]
        if not any(row.get("sessionId") == target for row in registry.entries()):
            print(
                f"  note: no live session is registered as {target}, so nobody is currently "
                "addressed by this. It stays open until some session moves it; any session can."
            )
    if not record["from"].get("session_id"):
        # Said out loud rather than left as an absent field. The recipient sees a handoff from a cwd
        # and no name, and "who sent this" is the first thing they will ask.
        print(
            "  note: the registry has no entry for this process, so it is recorded as coming from "
            f"{args.cwd} with no session or name."
        )
    # The handoff is written either way - an unreadable marker is not a reason to refuse a post -
    # but the exit code says so, as it does everywhere else a problem line is printed.
    return 1 if config_problem else 0


def _transition(args, status):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    own = registry.own_entry() or {}
    move, problem = handoffs.set_status(
        resolution.root, args.id, status, by=own.get("name"), note=args.note
    )
    if problem:
        print(f"problem: {problem}")
        return 1
    print(f"{args.id} is now {move['status']}")
    return 0


def cmd_handoff_accept(args):
    # Accepting is explicitly not closing, in the CLI as well as in the schema. Two subcommands
    # rather than `--status`, so taking something on cannot be typed as finishing it.
    return _transition(args, handoffs.ACCEPTED)


def cmd_handoff_close(args):
    return _transition(args, handoffs.CLOSED)


def cmd_handoff_resolve(args):
    # A separate verb rather than `--force` on `close`, and this is the one command here that
    # writes a status nothing derived from the moves already on disk. Keeping it separate is what
    # stops the everyday verbs from being able to do it by accident: `accept` and `close` refuse a
    # handoff with no current status, and that refusal is correct, so the way out has to be typed
    # on purpose.
    resolution = _resolved(args)
    if resolution is None:
        return 1
    own = registry.own_entry() or {}
    move, problem = handoffs.resolve(
        resolution.root, args.id, args.status, by=own.get("name"), note=args.note
    )
    if problem:
        print(f"problem: {problem}")
        return 1
    print(f"{args.id} is now {move['status']}, resolved at position {move['after']}")
    # Said every time, because the tie is still there and every later reader will still report it.
    # A command that looked like it had cleaned something up would be the wrong impression to leave:
    # what it did was add a decision on top of a disagreement that stays on the record.
    print("  the moves that disagree are still on disk and still reported; nothing was removed.")
    return 0


def cmd_handoff_list(args):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    root = resolution.root
    config, config_problem = store.config(root)
    stored, problems = handoffs.load_all(root)
    if config_problem:
        problems = [config_problem, *problems]
    matching = [pair for pair in stored if args.all or pair[1] != handoffs.CLOSED]
    # Newest first, so the cap below keeps the newest. `load_all` returns filename order, which for
    # timestamp-prefixed ids is oldest first, and a cap over that hides the handoff somebody posted
    # a minute ago behind a count - the thing #61 is about, arriving through the fix for it. Sorted
    # on the record rather than reversing what the store returned, so this does not quietly depend
    # on a sort order two modules away.
    matching.sort(key=lambda pair: (pair[0]["created"], pair[0]["id"]), reverse=True)
    # #61: `max_handoffs_listed` was in the schema, had a default, was asserted to have one, and no
    # code read it. A setting nothing reads is worse than no setting, because somebody raises it and
    # believes they have seen the rest.
    cap = config["max_handoffs_listed"]
    shown = matching[:cap]
    width = config["max_focus_chars"]
    print(f"handoffs  {len(stored)} stored, {len(shown)} shown")
    for record, status in shown:
        print(f"  {record['id']}  {status}")
        print(
            f"    to {handoffs.describe(record['to'], width)}, "
            f"from {handoffs.describe_sender(record, width)}, {record['created']}"
        )
        print(f"    {handoffs.preview(record['body'], width)}")
    if len(matching) > len(shown):
        # Counted, and naming the lever and the file it is in. A list that stops at eight reads
        # exactly like a root with eight handoffs under it, which is the whole of #61. "Older",
        # because which end the cap took is the first thing the reader needs to know about it.
        print(
            f"  +{len(matching) - len(shown)} older not shown: raise max_handoffs_listed in "
            f"{store.marker_path(root)}"
        )
    for problem in problems:
        print(f"problem   {problem}")
    return 1 if problems else 0


def _cmd_migrate_step4(root, apply):
    config, problem = store.config(root)
    if problem:
        print(
            f"problem: the marker is unreadable, so the ledger it names cannot be found: {problem}"
        )
        return 1
    if "legacy_ledger" not in config:
        print(
            "Step 4 is not applicable: the marker names no `legacy_ledger`, so there is nothing"
            " to import. If this root did keep a markdown ledger, name it in"
            f" {store.marker_path(root)}."
        )
        return 0
    prepared = migrate.prepare(root, config["legacy_ledger"])
    plan = prepared.plan
    print(f"ledger    {prepared.path}")
    print(
        f"counts    {prepared.parsed} parsed, {len(plan.create)} to create, "
        f"{len(prepared.closes)} to close, {len(plan.unchanged)} unchanged, "
        f"{len(plan.skipped)} closed and skipped, {len(plan.orphan)} stored with no entry, "
        f"{len(prepared.drift)} drifted, {len(prepared.stranded)} stranded open, "
        f"{len(prepared.problems)} problem(s)"
    )
    for entry, to in zip(plan.create, prepared.routes):
        where = handoffs.describe(to, config["max_focus_chars"]) if to else "(no route)"
        dated = entry.date or "undated, so stamped with the time of the import"
        print(f"create    {dated}  {where}  {store.printable(entry.headline[:60])}")
    for change in prepared.closes:
        print(f"close     {change.record['id']}  closed in the ledger")
    for change, fields in prepared.drift:
        print(
            f"drift     {change.record['id']}  {', '.join(sorted(fields))}, reported, not written"
        )
    stranded = {record["id"] for record in prepared.stranded}
    for record in plan.orphan:
        if record["id"] in stranded:
            print(
                f"stranded  {record['id']}  open, and no longer in the ledger; close it with "
                "`exchange handoff close`, or restore the entry"
            )
        else:
            print(f"orphan    {record['id']}  closed, and no longer in the ledger")
    for problem in prepared.problems:
        print(f"problem   {problem}")
    if not apply:
        if prepared.problems:
            print(
                "dry run   nothing was written, and `--apply` refuses until the problems are fixed"
            )
        else:
            print("dry run   nothing was written; `--apply` writes it")
        return 1 if prepared.problems else 0
    lines, problems = migrate.apply(root, prepared)
    for line in lines:
        print(line)
    for problem in problems:
        print(f"problem   {problem}")
    return 1 if problems else 0


def _cmd_migrate_step7(root, apply):
    prepared = decommission.prepare(root)
    # Checked here rather than in `decommission`, since done for step 4 is `doctor`'s reading and
    # one reading is the point. The plan still prints, so the gate does not hide what is waiting,
    # and it only applies when there is something to write: it guards the writes, not the report.
    gate = []
    if prepared.edits or prepared.retire:
        done, why = _step4(root)
        if not store.marker_path(root).is_file():
            gate.append("step 5 is not done: this root has no marker; `exchange init` writes one")
        elif done not in (True, NOT_APPLICABLE):
            gate.append(f"step 4 is not done, and its hooks are what surface the ledger: {why}")
    prepared = prepared._replace(problems=[*gate, *prepared.problems])
    print(
        f"counts    {sum(len(names) for _, _, names in prepared.edits)} wiring(s) to remove in "
        f"{len(prepared.edits)} file(s), {len(prepared.retire)} script(s) to retire, "
        f"{len(prepared.keep)} kept, {len(prepared.problems)} problem(s)"
    )
    for path, _, names in prepared.edits:
        print(f"unwire    {', '.join(names)} in {path}")
    for path, name in prepared.machine_wide:
        print(
            f"machine   {name} in {path} fires for every root on this machine, so it is not edited"
            " from here; remove it there, or wherever that file is generated from"
        )
    for script in prepared.retire:
        print(f"retire    {script.name}, moved aside rather than deleted")
    for script in prepared.keep:
        print(f"keep      {script.name}, still wired machine-wide")
    if prepared.retire:
        print(
            "note      another root's settings cannot be read from here. One still wiring a retired"
            " script fails at its next session start; moving the file back undoes it"
        )
    for problem in prepared.problems:
        print(f"problem   {problem}")
    if not (prepared.edits or prepared.retire or prepared.problems):
        if prepared.machine_wide:
            print(
                "nothing   to do here. The machine-wide wiring above is the rest of step 7, and"
                " `doctor` reads it done once that and every script it keeps are gone"
            )
        else:
            print("nothing   to do here")
        return 0
    if not apply:
        if prepared.problems:
            print(
                "dry run   nothing was written, and `--apply` refuses until the problems are fixed"
            )
        else:
            print("dry run   nothing was written; `--apply` writes it")
        return 1 if prepared.problems else 0
    lines, problems = decommission.apply(prepared)
    for line in lines:
        print(line)
    for problem in problems:
        print(f"problem   {problem}")
    return 1 if problems else 0


def cmd_migrate(args):
    resolution = _resolved(args)
    if resolution is None:
        return 1
    if args.step == 7:
        return _cmd_migrate_step7(resolution.root, args.apply)
    return _cmd_migrate_step4(resolution.root, args.apply)


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

    handoff = sub.add_parser("handoff", help="post or answer a handoff")
    # `required=True` rather than defaulting to one of them. `exchange handoff` with no verb is
    # ambiguous between posting and listing, and picking either would make a typo do something.
    hsub = handoff.add_subparsers(dest="handoff_command", required=True)

    hpost = hsub.add_parser("post", help="post a handoff to a scope or to one session")
    hpost.add_argument("--repo", help="root-relative repository directory")
    hpost.add_argument("--path", action="append", default=[], help="repeatable; narrows --repo")
    hpost.add_argument("--session", help="address one live session instead of a scope")
    hpost.add_argument("--body", required=True, help="markdown; `-` reads stdin")
    hpost.set_defaults(func=cmd_handoff_post)

    haccept = hsub.add_parser("accept", help="take a handoff on, which is not closing it")
    haccept.add_argument("id")
    haccept.add_argument("--note")
    haccept.set_defaults(func=cmd_handoff_accept)

    hclose = hsub.add_parser("close", help="record a handoff as finished")
    hclose.add_argument("id")
    hclose.add_argument("--note")
    hclose.set_defaults(func=cmd_handoff_close)

    hresolve = hsub.add_parser(
        "resolve", help="declare the status of a handoff frozen by two disagreeing moves"
    )
    hresolve.add_argument("id")
    hresolve.add_argument(
        "--status", required=True, choices=handoffs.STATUSES, help="the status you are declaring"
    )
    # Required, unlike on `accept` and `close`. Those two record a move anyone can derive from what
    # the moves already say; this one records a judgement, and a judgement with no reason on it is
    # the thing the next reader of the tie cannot do anything with.
    hresolve.add_argument("--note", required=True, help="why this way rather than the other")
    hresolve.set_defaults(func=cmd_handoff_resolve)

    hlist = hsub.add_parser("list", help="handoffs under this root, open ones by default")
    hlist.add_argument("--all", action="store_true", help="include closed ones")
    hlist.set_defaults(func=cmd_handoff_list)

    migrate_ = sub.add_parser("migrate", help="run a migration step; a dry run unless --apply")
    # Required rather than defaulting to the next outstanding step. A command that writes into
    # the store should not pick what it writes from state the typist has not looked at.
    migrate_.add_argument("--step", type=int, choices=(4, 7), required=True)
    migrate_.add_argument(
        "--apply", action="store_true", help="write the plan; refused on any problem"
    )
    migrate_.set_defaults(func=cmd_migrate)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

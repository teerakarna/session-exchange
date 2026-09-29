#!/usr/bin/env python3
"""The CLI, run as a real command.

`HOME` is pointed at a tmpdir throughout, which isolates the session registry, the legacy scripts
and the user settings in one move. The registry fixture names this test process as the session's
pid, because that is how the CLI works out who is calling it: it walks up the process tree until a
pid matches a registry row, since a command run through a tool call has no other way to learn its
own session id and matching on cwd picks the wrong session the moment two of them share a directory.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
CLI = PLUGIN / "lib" / "cli.py"

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def scope_of(text, script):
    """The scope marker on `doctor`'s `wired:` line for `script`.

    Returns a description instead of raising when there is not exactly one such line, so a missing
    or duplicated line is a failed check with the count in it rather than a traceback that stops the
    rest of the file running.
    """
    lines = [line for line in text.splitlines() if "wired:" in line and script in line]
    if len(lines) != 1:
        return f"{len(lines)} wired lines naming {script}"
    return lines[0].rsplit("(", 1)[-1].strip().rstrip(")")


def fixture(tmp):
    """A synthetic HOME whose registry knows this test process, and an unmarked area with a repo."""
    tmp = pathlib.Path(tmp).resolve()
    sessions = tmp / "home" / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (tmp / "home" / ".claude" / "hooks").mkdir()
    (sessions / f"{os.getpid()}.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "sessionId": "real-one",
                "name": "the-caller",
                "cwd": str(tmp),
                "status": "busy",
            }
        )
    )
    area = tmp / "area"
    (area / "repo" / ".git").mkdir(parents=True)
    (area / "repo" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (area / "CLAUDE.md").write_text("area\n")
    return tmp / "home", area, area / "repo"


def run(home, cwd, *args, exchange_root="", stdin=None):
    done = subprocess.run(
        [sys.executable, str(CLI), "--cwd", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=30,
        input=stdin,
        env={**os.environ, "HOME": str(home)} | {"CC_EXCHANGE_ROOT": str(exchange_root)},
    )
    return done.returncode, done.stdout + done.stderr


print("with no root, every command explains itself rather than guessing")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    code, out = run(home, repo, "show")
    check(
        "show says there is no exchange here",
        (code, "no environment root" in out.lower()),
        (1, True),
    )
    check("and names what init would mark", str(area) in out, True)

print("init")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    code, out = run(home, repo, "init")
    check(
        "marks the area above the repo, not the repo",
        (code, (area / ".claude" / "exchange.json").is_file()),
        (0, True),
    )
    check("and not the repo itself", (repo / ".claude" / "exchange.json").exists(), False)
    check("and creates the store", (area / ".claude" / "exchange" / "handoffs").is_dir(), True)

    code, out = run(home, repo, "init")
    check(
        "running it again reports rather than rewrites", (code, "Already marked" in out), (0, True)
    )

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    # Two sibling areas that are not repos: marking the directory holding them would give each
    # sight of the other's sessions and handoffs, which is the one thing root resolution prevents.
    container = pathlib.Path(tmp) / "container"
    for name in ("one", "two"):
        (container / name).mkdir(parents=True)
        (container / name / "CLAUDE.md").write_text("area\n")
    (container / "CLAUDE.md").write_text("container\n")
    inner = container / "one" / "repo"
    (inner / ".git").mkdir(parents=True)

    code, out = run(home, inner, "init")
    check(
        "defaults to the area rather than the container",
        (code, (container / "one" / ".claude" / "exchange.json").is_file()),
        (0, True),
    )
    code, out = run(home, inner, "init", str(container))
    check(
        "and refuses the container when asked for it by name",
        (code, "Refusing to mark" in out, "separate workspaces" in out),
        (1, True, True),
    )
    check("nothing was written to the container", (container / ".claude").exists(), False)
    code, out = run(home, inner, "init", str(container), "--force")
    check(
        "--force is the only way past it",
        (code, (container / ".claude" / "exchange.json").is_file()),
        (0, True),
    )

with tempfile.TemporaryDirectory() as tmp:
    # The same container, wearing a `.git`. #33 asked for that to be an automatic pass, on the
    # grounds that a repo storing `CLAUDE.md` files looks like a directory of areas; it was built
    # and reverted, because the exemption also let this tree through with no `--force`. The refusal
    # stays and a note says which case it may be, since only a human can tell. This check is the one
    # that was missing when the exemption shipped: the fixture above has no `.git`, so it passed.
    home, area, repo = fixture(tmp)
    container = pathlib.Path(tmp) / "container"
    for name in ("one", "two"):
        (container / name).mkdir(parents=True)
        (container / name / "CLAUDE.md").write_text("area\n")
    (container / "CLAUDE.md").write_text("container\n")
    (container / ".git").mkdir()
    inner = container / "one" / "repo"
    (inner / ".git").mkdir(parents=True)

    code, out = run(home, inner, "init", str(container))
    check(
        "a container that is also a git root is still refused",
        (code, "Refusing to mark" in out, (container / ".claude").exists()),
        (1, True, False),
    )
    check(
        "and the refusal says it is a git root, rather than only repeating itself",
        "git root" in out,
        True,
    )

    # And the default never offers it either, which is the route that would have marked it silently.
    code, out = run(home, inner, "init")
    check(
        "and the default is the area, not the container it sits in",
        (code, (container / "one" / ".claude" / "exchange.json").is_file()),
        (0, True),
    )
    check("still nothing in the container", (container / ".claude").exists(), False)

print("claim")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")

    code, out = run(
        home, repo, "claim", "--focus", "the hooks manifest", "--path", "a", "--path", "b"
    )
    check("claims as the calling session, by name", (code, "the-caller" in out), (0, True))
    written = json.loads((area / ".claude" / "exchange" / "sessions" / "real-one.json").read_text())
    check(
        "and records what it was told",
        (written["name"], written["focus"], written["paths"], written["git_branch"]),
        ("the-caller", "the hooks manifest", ["a", "b"], "main"),
    )

    code, out = run(home, repo, "claim", "--path", "c")
    written = json.loads((area / ".claude" / "exchange" / "sessions" / "real-one.json").read_text())
    check("a second claim adds rather than replacing", written["paths"], ["a", "b", "c"])

    # Break it: the display name must come from the id being claimed as, not from whoever is
    # calling. Borrowing it labels someone else's claim with this session's name, and then shows
    # everybody a stale row under it.
    code, out = run(home, repo, "claim", "--session", "someone-else", "--focus", "other work")
    other_path = area / ".claude" / "exchange" / "sessions" / "someone-else.json"
    other = json.loads(other_path.read_text())
    check(
        "an explicit session id does not borrow the caller's name",
        ("name" in other, other["focus"]),
        (False, "other work"),
    )

    # Every list field, not just paths. These three are accepted, validated and written, so a
    # reader that renders one of them reports a subset of the claim as if it were the claim.
    run(home, repo, "claim", "--repo", "one", "--ticket", "T-1", "--ticket", "T-2")
    code, out = run(home, repo, "show")
    check(
        "show renders every claimed list, not only paths",
        ("repos: one" in out, "tickets: T-1, T-2" in out),
        (True, True),
    )

    # The cap is real and so is what it hides. Counting the remainder is the difference between a
    # short render and a render that looks complete.
    marker = area / ".claude" / "exchange.json"
    marker.write_text(json.dumps({"name": "area", "max_hot_paths": 2}))
    code, out = run(home, repo, "show")
    check("a capped list counts what it left out", "paths: a, b, +1 more" in out, True)

    marker.write_text(json.dumps({"name": "area"}))
    code, out = run(home, repo, "show")
    check("show lists both claims", (code, "claims    2" in out), (0, True))
    check(
        "with each session's focus",
        ("the hooks manifest" in out, "other work" in out),
        (True, True),
    )
    check(
        "and marks the one with no live session as stale", "no longer in the registry" in out, True
    )

    # #46 on the other side of the comparison it was filed about. The guard was on `handoff post`
    # alone for one commit, which contains nothing: the matcher compares `to.repo` against a claim's
    # `repos`, so an absolute path refused on one route arrives by the other. Three flags, because
    # `--set-path` writes the field `--path` appends to and a guard on two of the three is the same
    # bug one flag over.
    for flag, value in (
        ("--repo", "/etc"),
        ("--repo", "../../../../etc"),
        ("--path", "/etc/shadow"),
        ("--path", "a/../../b"),
        ("--set-path", "/etc"),
    ):
        code, out = run(home, repo, "claim", flag, value)
        check(
            f"claim {flag} {value} is refused, as it is on a handoff",
            (code, "problem:" in out),
            (1, True),
        )
    code, out = run(home, repo, "claim", "--repo", "\t/etc")
    check(
        "and so is one that only renders as an absolute path",
        (code, "cannot hold characters a terminal does not show" in out),
        (1, True),
    )
    # The codepoint, not only the shape it renders as. `/etc` on its own is a string the typist can
    # see nothing wrong with, so a refusal carrying that alone is one they cannot act on.
    check("and the refusal names what to remove", "U+0009" in out, True)
    written = json.loads((area / ".claude" / "exchange" / "sessions" / "real-one.json").read_text())
    check("and none of them reached the record", written["repos"], ["one"])
    code, out = run(home, repo, "claim", "--repo", "two/../two")
    check("a .. in the middle is refused as well as one at the front", code, 1)
    # Not a blanket refusal of anything with dots in it, which is the way a guard like this usually
    # goes wrong: `..` is a whole component or it is nothing.
    code, out = run(home, repo, "claim", "--repo", "a..b")
    check("an ordinary repo whose name merely contains dots still claims", code, 0)

print("another session's claim does not get to drive the reader's terminal")

with tempfile.TemporaryDirectory() as tmp:
    # The claim half of #47. `show` renders five fields off someone else's claim and none of them
    # carries a pattern in the schema - `focus` is described as "in its own words". It rendered all
    # five raw. A human's terminal is the whole of the reach today: `hook.py` renders no claim
    # content and says presence rendering lands next, so nothing here reaches a model's context yet.
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    nasty = "HARMLESS\033[2K\033[1;31mURGENT\007"
    code, out = run(
        home, repo, "claim", "--session", "peer-1", "--focus", nasty, "--ticket", "T\0071"
    )
    peer = area / ".claude" / "exchange" / "sessions" / "peer-1.json"
    stored = json.loads(peer.read_text())
    # Stored verbatim, like a handoff body: the store is not the place to edit someone's prose.
    check("the claim keeps the focus exactly as it was written", stored["focus"], nasty)
    # The echo is a render too, and it was the one the first cut of this block missed while it fixed
    # `show`. With `--session` the record being read back belongs to another session, so these lines
    # carry that session's text, and `--focus` is the flag whose whole job is free text.
    check(
        "and the echo confirming it is inert as well",
        ("\033" in out, "\007" in out, "focus: HARMLESS[2K[1;31mURGENT" in out),
        (False, False, True),
    )
    check("including a list field in that echo", ("T1" in out, "\007" in out), (True, False))

    code, out = run(home, repo, "show")
    check(
        "and show renders it inert",
        ("\033" in out, "\007" in out, "HARMLESS[2K[1;31mURGENT" in out),
        (False, False, True),
    )
    # The name comes out of the registry, which is another session's process rather than this one's.
    stored["name"] = "peer\033[2Kx"
    peer.write_text(json.dumps(stored))
    code, out = run(home, repo, "show")
    check(
        "a display name another session chose renders inert too",
        ("\033" in out, "peer[2Kx" in out),
        (False, True),
    )
    # And in the echo, which is the other render of the same field. The claim already holds the name
    # by now, so `claim` echoes it back without the registry being involved a second time.
    code, out = run(home, repo, "claim", "--session", "peer-1", "--ticket", "T2")
    check(
        "and in the line the echo leads with",
        ("\033" in out, "claimed as peer[2Kx" in out),
        (False, True),
    )
    # A list field, and not only its first element. Re-read before editing: the `claim` above wrote
    # a ticket and a fresh timestamp, and putting back the dict that was read before it would drop
    # both, leaving a check further down asserting against a record this file had already replaced.
    stored = json.loads(peer.read_text())
    stored["paths"] = ["ok", "two\033[2K"]
    peer.write_text(json.dumps(stored))
    code, out = run(home, repo, "show")
    check(
        "and so does every element of a list field",
        ("\033" in out, "ok, two[2K" in out),
        (False, True),
    )
    # And that same field through the echo, which is where the guard on the way in stops being the
    # answer: `--path` is held by `store.scope_fault`, but this `paths` was written into the file
    # directly, the way an older record, the `migrate` importer or a hand edit writes one.
    code, out = run(home, repo, "claim", "--session", "peer-1")
    check(
        "a scope the guard never saw is still inert when the echo reads it back",
        ("\033" in out, "paths: ok, two[2K" in out),
        (False, True),
    )

print("doctor")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    code, out = run(home, repo, "doctor")
    check("reports the root and the rule that found it", (code, "by marker" in out), (0, True))
    check("names the first outstanding step", "next      step 4" in out, True)
    # A diagnostic that quietly omits a check reads exactly like one that passed it.
    check("prints the checks it cannot answer rather than skipping them", "[?]" in out, True)
    check("says why each one is unanswerable", "not checkable here" in out, True)
    check("no legacy scripts in this synthetic home", "0 script(s) on disk" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    # The override is the only way to a root with no marker, since the walk finds a root by finding
    # one. `store.config` hands back the defaults and no problem, which is correct for a renderer
    # and must not be printed as a marker that was read.
    code, out = run(home, repo, "doctor", exchange_root=area)
    check(
        "a root with no marker is reported absent, not valid",
        ("marker    absent" in out, "marker    valid" in out),
        (True, False),
    )
    check("and it agrees with step 5 instead of contradicting it", "[ ] 5." in out, True)
    check("an unconfigured root is not a fault on its own", code, 0)

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    LEGACY_COMMAND = 'python3 "$HOME/.claude/hooks/session_exchange_handoffs.py"'
    hooks = home / ".claude" / "hooks"
    (hooks / "session_exchange_handoffs.py").write_text("# legacy\n")
    (hooks / "review-requests-check.sh").write_text("# unrelated\n")
    (home / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": LEGACY_COMMAND,
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )

    code, out = run(home, repo, "doctor")
    check("a wired legacy script is a fault, not a note", code, 1)
    # The wiring is in the user's own settings and `home` is not under `area`, so this is the
    # machine-wide fault rather than this root being rendered twice. Matching on `DOUBLE FIRE:` with
    # the colon rather than bare: the CROSS ROOT message names DOUBLE FIRE to say it is *not* that
    # one, so the bare substring passed against the wrong message for as long as it was written that
    # way, which is a check that had stopped being able to fail.
    check(
        "a machine-wide wiring is called that, and not a doubled fire",
        ("CROSS ROOT" in out, "DOUBLE FIRE:" in out),
        (True, False),
    )
    check(
        "the wiring is marked with the scope it has",
        scope_of(out, "session_exchange_handoffs.py"),
        "machine-wide",
    )
    check("the unrelated hook is left out of it", "review-requests" in out, False)
    check("step 7 is outstanding while it is wired", "next      step 4" in out, True)

    # The same script, wired again in a settings file under the root. Now both faults are live, and
    # each warning has to name only the wiring that is its own - a DOUBLE FIRE naming the user's
    # settings sends the reader hunting through files under the root that never mention it.
    (area / ".claude" / "settings.local.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'bash "$HOME/.claude/hooks/alpha-session-lane.sh"',
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    code, out = run(home, repo, "doctor")
    check(
        "both faults are reported, not whichever was found first",
        (code, "DOUBLE FIRE:" in out, "CROSS ROOT" in out),
        (1, True, True),
    )
    # Read off each script's own line rather than from the whole output: two markers present
    # somewhere is what a swap of the two would also look like, and the marker is the only thing
    # here that says which file to go and edit.
    check(
        "and each wiring line carries the scope of its own settings file",
        (scope_of(out, "alpha-session-lane.sh"), scope_of(out, "session_exchange_handoffs.py")),
        ("this root", "machine-wide"),
    )

print("handoff")


def posted_id(text):
    """The id out of `posted <id> to ...`, or a description of why there is not one."""
    lines = [line for line in text.splitlines() if line.startswith("posted ")]
    if len(lines) != 1:
        return f"{len(lines)} posted lines in {text!r}"
    return lines[0].split()[1]


with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    store_dir = area / ".claude" / "exchange" / "handoffs"

    code, out = run(home, repo, "handoff", "post", "--body", "look at the hooks manifest")
    check(
        "post with no addressing refuses and says which flags exist",
        (code, "--repo" in out and "--session" in out),
        (1, True),
    )
    check("and writes nothing", list(store_dir.iterdir()), [])

    code, out = run(home, repo, "handoff", "post", "--repo", "one", "--session", "s", "--body", "x")
    check("a scope and a session at once is refused", (code, "not both" in out), (1, True))

    code, out = run(home, repo, "handoff", "post", "--path", "a", "--body", "x")
    check("--path without --repo is refused too", (code, "needs --repo" in out), (1, True))

    code, out = run(home, repo, "handoff", "post", "--repo", "one", "--body", "   ")
    check("an empty body is refused", (code, "says nothing" in out), (1, True))

    code, out = run(
        home,
        repo,
        "handoff",
        "post",
        "--repo",
        "repo",
        "--path",
        "plugin/lib",
        "--body",
        "-",
        stdin="the manifest is wired twice\n\nsee `doctor`\n",
    )
    first = posted_id(out)
    check("a body on stdin is posted", (code, (store_dir / f"{first}.json").is_file()), (0, True))
    written = json.loads((store_dir / f"{first}.json").read_text())
    # `.d`, not the bare id: an id may contain a dot, and a directory named after the bare id would
    # then sit exactly where another id's record goes.
    moves = store_dir / f"{first}.d"
    check(
        "recorded whole, as the caller, with no state in the record and no moves beside it",
        (
            written["from"]["name"],
            written["to"],
            "status" in written,
            "history" in written,
            moves.exists(),
            written["body"].endswith("see `doctor`"),
        ),
        ("the-caller", {"repo": "repo", "paths": ["plugin/lib"]}, False, False, False, True),
    )

    code, out = run(home, repo, "handoff", "list")
    check(
        "list shows it with its scope and first line",
        (code, first in out, "repo: plugin/lib" in out, "the manifest is wired twice" in out),
        (0, True, True, True),
    )

    code, out = run(home, repo, "handoff", "accept", first, "--note", "taking it")
    check("accept moves it without closing it", (code, "is now accepted" in out), (0, True))
    # Read off the filesystem rather than through `handoffs`, because the point is the layout: one
    # new file under the id, and the record the sender wrote left exactly as it was.
    recorded = [json.loads(p.read_text()) for p in sorted(moves.glob("*.json"))]
    check(
        "by writing one move beside the record rather than into it",
        (
            [e["status"] for e in recorded],
            # `.get` through an index that may not exist. When the rule under test is the one that
            # broke there is no move to index, and an IndexError would report one broken rule as a
            # broken test file and take the rest of this fixture down with it.
            recorded[0].get("by") if recorded else None,
            json.loads((store_dir / f"{first}.json").read_text()) == written,
        ),
        (["accepted"], "the-caller", True),
    )

    code, out = run(home, repo, "handoff", "close", first)
    check("close then hides it from the default list", (code, "is now closed" in out), (0, True))
    code, out = run(home, repo, "handoff", "list")
    check("which counts what it is not showing", "1 stored, 0 shown" in out, True)
    code, out = run(home, repo, "handoff", "list", "--all")
    check("--all brings it back", first in out, True)

    # Closing a closed handoff is not absorbed as a no-op: it means a stale render or two sessions
    # answering the same thing, and a second identical move would hide both.
    code, out = run(home, repo, "handoff", "close", first)
    check("closing it again is refused", (code, "already closed" in out), (1, True))
    check("and no third move was written", len(list(moves.glob("*.json"))), 2)

    code, out = run(home, repo, "handoff", "accept", "no-such-id")
    check("an unknown id is named, not swallowed", (code, "no handoff" in out), (1, True))

with tempfile.TemporaryDirectory() as tmp:
    # Two moves made against the same state - what two sessions closing one handoff at the same
    # moment leave behind. Both are kept, because neither write is a rewrite of the other's file,
    # and the contradiction is reported rather than resolved in favour of whichever sorted last.
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    code, out = run(home, repo, "handoff", "post", "--repo", "repo", "--body", "first")
    handoff_id = posted_id(out)
    run(home, repo, "handoff", "close", handoff_id)
    moves = area / ".claude" / "exchange" / "handoffs" / f"{handoff_id}.d"
    forged = {"at": "2026-01-02T03:04:05Z", "status": "accepted", "after": 0}
    (moves / "0000-forged.json").write_text(json.dumps(forged))

    code, out = run(home, repo, "handoff", "list")
    check(
        "two moves at one position are a fault, and the row is still shown",
        (code, "position 0" in out, handoff_id in out),
        (1, True, True),
    )
    code, out = run(home, repo, "handoff", "accept", handoff_id)
    check(
        "and a move is refused rather than filed after a position with no last entry",
        (code, "cannot be worked out" in out),
        (1, True),
    )
    code, out = run(home, repo, "show")
    check("show reports it too, rather than rendering a count over it", code, 1)

with tempfile.TemporaryDirectory() as tmp:
    # A record from before #44, with `status` and `history` in it. `additionalProperties` is false,
    # so it is refused by name rather than half-read - the row leaves the list and a problem says
    # which file and which key. The alternative was reading the record and ignoring the two
    # fields, which would silently reopen every handoff that had been closed under the old shape.
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    code, out = run(home, repo, "handoff", "post", "--repo", "repo", "--body", "first")
    handoff_id = posted_id(out)
    path = area / ".claude" / "exchange" / "handoffs" / f"{handoff_id}.json"
    legacy = json.loads(path.read_text())
    legacy["status"] = "closed"
    legacy["history"] = [{"at": legacy["created"], "status": "closed"}]
    path.write_text(json.dumps(legacy))

    code, out = run(home, repo, "handoff", "list")
    check(
        "a record carrying its own status is refused by name, not read around",
        (code, "unexpected key 'status'" in out, "0 stored" in out),
        (1, True, True),
    )

print("a handoff addressed to a session nobody is running says so while it can")

with tempfile.TemporaryDirectory() as tmp:
    # #45 decided that addressing is a hint rather than access control, so the mistyped id is the
    # only real failure left in it, and a note at post time is the whole fix. Both halves are
    # checked here: the note when nothing holds the id, and no note when something does - a warning
    # that fires either way says nothing, and that is the easier of the two to ship by accident.
    home, area, repo = fixture(tmp)
    run(home, repo, "init")

    code, out = run(home, repo, "handoff", "post", "--session", "no-such-session", "--body", "hi")
    check(
        "an unheld id is a note, not a refusal, and the handoff is posted",
        (code, "no live session is registered as no-such-session" in out, "posted" in out),
        (0, True, True),
    )
    check(
        "and the note says any session can move it, since that is what was decided",
        "any session can" in out,
        True,
    )

    # The fixture registers this test process, so its own session id is one the registry holds.
    own = json.loads(next((pathlib.Path(home) / ".claude" / "sessions").glob("*.json")).read_text())
    code, out = run(home, repo, "handoff", "post", "--session", own["sessionId"], "--body", "hi")
    check(
        "a live id gets no note, or the warning means nothing",
        (code, "no live session is registered" in out),
        (0, False),
    )

print("another session's text does not get to drive the reader's terminal")

with tempfile.TemporaryDirectory() as tmp:
    # End to end, and the reason it is here as well as in `test_handoffs.py`: the rule lives in
    # `handoffs` so the sweep can reach it, and nothing stops a later edit inlining the rendering
    # back into `cli`, where it would be correct on the day and unswept afterwards. This check is
    # what would notice. `cli` is in DECLINED on the argument that its output is wrong in front of
    # the person who typed the command, and that argument is exactly what fails here: an erase-line
    # escape makes the output look right to the only witness.
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    nasty = "HARMLESS\033[2K\033[1;31mURGENT\007"
    code, out = run(home, repo, "handoff", "post", "--repo", "repo", "--body", nasty)
    handoff_id = posted_id(out)

    stored = json.loads(
        (area / ".claude" / "exchange" / "handoffs" / f"{handoff_id}.json").read_text()
    )
    # Stored verbatim. The store is not the place to edit someone's prose, and a body that came back
    # altered would be a worse bug than the one being fixed: the record is the evidence.
    check("the record keeps the body exactly as it was posted", stored["body"], nasty)

    code, out = run(home, repo, "handoff", "list")
    check(
        "and the rendered line carries no escape at all",
        (code, "\033" in out, "\007" in out, "HARMLESS[2K[1;31mURGENT" in out),
        (0, False, False, True),
    )
    # Not just the body. Three fields on that block come from the sender. `to` used to be reachable
    # with an escape in it and is not any more: `scope_fault` refuses a scope whose printable form
    # differs from the value, because a stored scope that renders as something else is both a
    # misleading line and two things the matcher cannot tell apart. So the CLI path is a refusal
    # now.
    code, out = run(home, repo, "handoff", "post", "--repo", "r\033[2Kp", "--body", "scope")
    check(
        "a repo with an escape in it is refused rather than posted",
        (code, "\033" in out, "cannot hold characters a terminal does not show" in out),
        (1, False, True),
    )
    check("and that refusal names the codepoint rather than only the shape", "U+001B" in out, True)

    # And the rendering still strips, which is the half that refusal does not cover. Written
    # straight to disk here, because that is the case that remains: a record an importer wrote, or
    # one that predates the guard, or anything else that is not this CLI. Without this the
    # `describe` stripping would have no end-to-end check left at all, since the only caller that
    # could produce the input now refuses to - which is how a guard added upstream quietly retires
    # the one downstream.
    aged = dict(stored, id="20260101T000000Z-aaaaaa", to={"repo": "r\033[2Kp"})
    (area / ".claude" / "exchange" / "handoffs" / f"{aged['id']}.json").write_text(json.dumps(aged))
    code, out = run(home, repo, "handoff", "list")
    check(
        "a record written by something other than this CLI still renders inert",
        (code, "\033" in out, "to r[2Kp" in out),
        (0, False, True),
    )

print("what is not built yet says so, and does not look like a failure")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    code, out = run(home, repo, "migrate")
    check(
        "migrate exits 2 and names the step",
        (code, "step 4" in out, "Nothing was changed" in out),
        (2, True, True),
    )
    # `handoff` is built now, but it has no default verb: guessing between posting and listing would
    # make a typo do something. Argparse's own exit 2, not the not-built one.
    code, out = run(home, repo, "handoff")
    check(
        "handoff with no verb is a usage error naming the verbs",
        (code, "post" in out, "not built yet" in out),
        (2, True, False),
    )

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

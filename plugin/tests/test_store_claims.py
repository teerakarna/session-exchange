#!/usr/bin/env python3
"""The store and the claims on top of it.

Two properties carry most of the weight, and both are asserted by breaking them:

- An invalid object never reaches disk. Validating after writing would leave a reader having to tell
  a corrupt file from one written by a newer version, which is a distinction nobody can make.
- A file that exists and cannot be read is never reported as "nothing here". Collapsing those two is
  how a dead parser read as a quiet day for ten days.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import claims
import store
import validate

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


CLAIM_SCHEMA = validate.load("claim")

print("write, read, and the difference between missing and unreadable")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    good = {"session_id": "s1", "cwd": str(root), "updated_at": store.now()}
    path = claims.path(root, "s1")

    check("a valid claim writes", store.write_json(path, good, CLAIM_SCHEMA), None)
    check("and reads back", store.read_json(path, CLAIM_SCHEMA), (good, None))
    check(
        "a missing file is nothing here, not a problem",
        store.read_json(claims.path(root, "absent"), CLAIM_SCHEMA),
        (None, None),
    )

    path.write_text("{ truncated")
    obj, problem = store.read_json(path, CLAIM_SCHEMA)
    check("a file that exists and will not parse says so", (obj, problem is not None), (None, True))

    path.write_text(json.dumps({"session_id": "s1"}))
    obj, problem = store.read_json(path, CLAIM_SCHEMA)
    check(
        "a file that parses and is invalid also says so",
        (obj, "updated_at" in (problem or "")),
        (None, True),
    )

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    path = claims.path(root, "s1")
    problem = store.write_json(path, {"session_id": "s1"}, CLAIM_SCHEMA)
    # Break it: if validation happened after the write, or not at all, the file would be here.
    check(
        "an invalid claim never reaches disk", (problem is not None, path.exists()), (True, False)
    )
    check(
        "and no stray temp file is left behind",
        sorted(p.name for p in path.parent.glob("*")) if path.parent.is_dir() else [],
        [],
    )

print("creating a file, as distinct from writing one")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    path = claims.path(root, "s1")
    first = {"session_id": "s1", "cwd": str(root), "updated_at": store.now()}

    check("a name nothing holds is created", store.create_json(path, first, CLAIM_SCHEMA), None)
    second = dict(first, cwd=str(root / "elsewhere"))
    check(
        "the same name again is refused rather than replaced",
        store.create_json(path, second, CLAIM_SCHEMA),
        f"{path.name} already exists; refusing to overwrite it",
    )
    # The refusal is the filesystem's, so what matters is that the first writer's bytes are still
    # there - not that a guard ran. `os.link` cannot half-succeed, which is the whole reason it is
    # used here rather than `exists()` and then a write.
    check("and the first contents are still there", store.read_json(path)[0], first)
    check(
        "with no temp file left beside it",
        sorted(p.name for p in path.parent.glob(".tmp-*")),
        [],
    )

print("an identifier that is also a filename")

check("a plain id passes", store.safe_id("abc-123.def"), "abc-123.def")
# `"sess-1\n"` is in this list because it was not refused: the pattern is anchored at both ends and
# Python's `$` still matches before a trailing newline, so `match` let it through, a claim was
# written under that filename, and the newline landed in the `session_id` field. Presence rendering
# puts that field in a markdown table cell, where a newline ends the row. The guard looked tight.
for bad in ("../escape", "a/b", "", None, "with space", "sess-1\n", "a\nb"):
    check(f"{bad!r} is refused rather than rewritten", store.safe_id(bad), None)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    claim, problem = claims.seed(root, "../../evil", root)
    check("seeding with a traversing id writes nothing", (claim, problem is not None), (None, True))
    check("and nothing appeared outside the store", list(root.parent.glob("evil*")), [])

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    claim, problem = claims.seed(root, "sess-1\n", root)
    check(
        "seeding with a newline in the id writes nothing",
        (claim, problem is not None),
        (None, True),
    )
    check(
        "and leaves no file named after it",
        sorted(p.name for p in root.rglob("*.json")),
        [],
    )

print("seed, update, clear")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/feat/thing\n")

    claim, problem = claims.seed(root, "s1", root, name="pane-a")
    check(
        "a seeded claim carries what the payload knows",
        (claim["session_id"], claim["name"], claim.get("git_branch"), problem),
        ("s1", "pane-a", "feat/thing", None),
    )

    (root / ".git" / "HEAD").write_text("9d4f1c0e" * 5 + "\n")
    claim, _ = claims.seed(root, "s1", root)
    check("a detached head is no branch rather than a sha-shaped one", "git_branch" in claim, False)

    claims.update(root, "s1", focus="the thing", add={"paths": ["a", "b"]})
    claim, _ = claims.update(root, "s1", add={"paths": ["b", "c"], "repos": ["dotfiles"]})
    check(
        "adding to a list deduplicates rather than repeating",
        (claim["paths"], claim["repos"]),
        (["a", "b", "c"], ["dotfiles"]),
    )

    # SessionStart fires again on resume and on compact. Wiping the focus then would be a
    # regression the session itself cannot see.
    claim, _ = claims.seed(root, "s1", root)
    check(
        "re-seeding keeps what the session said about itself",
        (claim["focus"], claim["paths"]),
        ("the thing", ["a", "b", "c"]),
    )

    claim, _ = claims.update(root, "s1", replace={"paths": ["only"]})
    check("replacing a list replaces it", claim["paths"], ["only"])
    claim, _ = claims.update(root, "s1", clear_fields=["paths"])
    check("clearing removes the field entirely", "paths" in claim, False)

    held, problems = claims.load_all(root)
    check("one claim under this root", (len(held), problems), (1, []))

    check("clearing a claim succeeds", claims.clear(root, "s1"), None)
    check("and the file is gone", claims.path(root, "s1").exists(), False)
    # SessionEnd can fire for a session that never claimed, and can fire twice.
    check("clearing again is still success", claims.clear(root, "s1"), None)

    claim, problem = claims.update(root, "s1", focus="x")
    check(
        "updating a claim that does not exist explains itself",
        (claim, problem is not None),
        (None, True),
    )

print("one unreadable file does not hide the readable ones, or the reverse")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    claims.seed(root, "s1", root)
    claims.seed(root, "s2", root)
    (store.sessions_dir(root) / "s3.json").write_text("{ nope")
    held, problems = claims.load_all(root)
    check("two read, one reported", (len(held), len(problems)), (2, 1))

print("the marker's defaults come from the schema, not from a second copy of them")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    (root / ".claude").mkdir()
    (root / ".claude" / "exchange.json").write_text(json.dumps({"name": "personal"}))
    config, problem = store.config(root)
    check(
        "a marker with only a name still yields every cap",
        (config["name"], config["stale_days"], config["max_handoffs_listed"], problem),
        ("personal", 7, 8, None),
    )

    (root / ".claude" / "exchange.json").write_text(json.dumps({"name": "x", "stale_days": "7"}))
    config, problem = store.config(root)
    # Refusing to render because one cap is misspelt would be the wrong trade. Doing it silently
    # would be worse than either.
    check(
        "an invalid marker yields defaults and a problem, not one or the other",
        (config["stale_days"], problem is not None),
        (7, True),
    )

print("the rules a sweep found nothing asserting")

# Every check below exists because a mutation of the rule it names survived. The pattern in what
# survived is worth naming: the happy path of `seed`, `update` and `clear` was asserted thoroughly,
# and every failure path of all three was asserted by nothing. A claim that could not be written and
# one that was written look the same to a caller that only ever reads the success case.

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / "deep" / "nested").mkdir(parents=True)

    # The walk up. `cwd` is wherever the session was started, which is usually not the repo root,
    # and the checks above only ever asked from the root - so stopping at `cwd` would have passed
    # every one of them and lost the branch for anyone working in a subdirectory.
    check(
        "the branch is found from a subdirectory, not only from the repo root",
        claims.git_branch(root / "deep" / "nested"),
        "main",
    )

    # A HEAD that is not valid UTF-8. This runs inside `seed`, so an exception here is not a missing
    # branch, it is no claim written at all: the session would be invisible to every other one
    # because a byte on disk was wrong. Decoding is not an `OSError`, which is why the guard next to
    # this one had to be widened before the check could be written.
    (root / ".git" / "HEAD").write_bytes(b"ref: refs/heads/\xff\xfe\n")
    try:
        branch = claims.git_branch(root)
    except Exception as exc:
        branch = f"raised {type(exc).__name__}"
    check("a HEAD that cannot be read is no branch, and not an exception either", branch, None)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    # A directory where the claim file goes. Contrived as a cause, ordinary as an effect: a full
    # disk, a read-only mount and a permission change all arrive at the same place, and the caller
    # has to be able to tell "claimed" from "did not claim".
    claims.path(root, "s1").mkdir(parents=True)
    claim, problem = claims.seed(root, "s1", root)
    check(
        "a seed that could not be written returns the problem, not the claim",
        (claim, problem is not None),
        (None, True),
    )

    # And the same file standing in the way of `clear`. Returning None here would leave a claim on
    # disk that presence goes on rendering, so a session that ended reads as a live peer.
    problem = claims.clear(root, "s1")
    check("a claim that could not be cleared says so", problem is not None, True)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    claims.seed(root, "s1", root)

    # `update` gets its id from the same payload `seed` does, but it is also reachable from
    # `exchange claim`, so it does its own check rather than trusting the caller's.
    claim, problem = claims.update(root, "s1/../escape", focus="x")
    check(
        "an unusable session id is refused by update too, not only by seed",
        (claim, problem is not None),
        (None, True),
    )

    claims.update(root, "s1", focus="the thing")
    claim, _ = claims.update(root, "s1", focus="")
    # `if focus:` instead of `if focus is not None:` is the same mistake as reading an empty string
    # as an absent argument, and it means there is no way to say "I am no longer on anything".
    check("an empty focus is a focus being cleared, not an argument not passed", claim["focus"], "")

    claim, _ = claims.update(root, "s1", replace={"paths": ["a", "a", "b"]})
    check("replacing a list deduplicates it, the same as adding does", claim["paths"], ["a", "b"])

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    # Seeded by hand with a timestamp from years ago rather than by calling `seed` twice: `now()` is
    # seconds-precision, so two calls in the same second are the same string and the check would
    # pass or fail on how fast the machine is.
    was = "2020-01-01T00:00:00Z"
    store.write_json(
        claims.path(root, "s1"),
        {"session_id": "s1", "cwd": str(root), "updated_at": was},
        CLAIM_SCHEMA,
    )
    claim, _ = claims.update(root, "s1", focus="speaking now")
    check(
        "an update touches the timestamp, or a session that just spoke reads as stale",
        claim["updated_at"] != was,
        True,
    )

print("text one session wrote and another one's terminal renders")

# The escape from the reproduction in #47, kept verbatim rather than described, because the point of
# the bug was that a description of the output and the output itself were different things.
check(
    "an erase-line escape does not survive to the terminal",
    store.printable("HARMLESS\033[2K\033[1;31mURGENT\007"),
    "HARMLESS[2K[1;31mURGENT",
)
check(
    "a carriage return goes, being the cheap way to do the same thing",
    store.printable("a\rb"),
    "ab",
)
check(
    "and so does a bidi override, which nobody here thought of and a blacklist would have missed",
    store.printable("safe\u202egnorw"),
    "safegnorw",
)
# The argument against `repr`, as a check rather than as a sentence in the docstring: if this ever
# fails, prose has started paying for the escapes.
check(
    "ordinary prose keeps its quotes, backslashes and spaces",
    store.printable("""it's a c:\\path, "quoted", 50% done"""),
    """it's a c:\\path, "quoted", 50% done""",
)
check(
    "a tab goes, because in a one-line preview it is there to move the cursor",
    store.printable("a\tb"),
    "ab",
)
check("an empty string is not a special case", store.printable(""), "")
# The other direction of the predicate. Without these, narrowing the rule to ASCII would pass every
# check above it and quietly take every non-English claim in the store with it: the prose check
# three above is ASCII-only, so it is a check of the example rather than of the rule.
check(
    "accented Latin survives, the stripper being about terminals and not about ASCII",
    store.printable("café déjà vu"),
    "café déjà vu",
)
check(
    "so does CJK, which is where a terminal-width argument would have gone wrong",
    store.printable("日本語のテキスト"),
    "日本語のテキスト",
)
check(
    "and Thai, Arabic and Devanagari, none of which a Latin blacklist would have considered",
    store.printable("ทดสอบ مرحبا नमस्ते"),
    "ทดสอบ مرحبا नमस्ते",
)
check("and a single emoji", store.printable("shipped 🚀"), "shipped 🚀")
# What the rule costs, asserted rather than left in a docstring, so that the cost is a thing someone
# has to edit a check to change. U+3000 is the ordinary space in Japanese prose and U+200D holds an
# emoji family together; both are swept up by "would a terminal show this" and both are a real loss.
check(
    "an ideographic space goes, which is a cost of the rule and not a win",
    store.printable("日本\u3000語"),
    "日本語",
)
check(
    "and a zero-width joiner, which splits a family emoji into three people",
    store.printable("\U0001f468\u200d\U0001f469\u200d\U0001f467"),
    "\U0001f468\U0001f469\U0001f467",
)

print()
print("and bounded in width, one line of it being all a reader gets")

check("text inside the cap is untouched", store.capped_text("abcdef", 6), "abcdef")
# The boundary in the other direction. `>= cap` was the first cut and appended "+0 more chars" to a
# line nothing had been cut from, which is a false statement in the one place this function exists
# to make a true one.
check(
    "one character over, and the remainder is counted",
    store.capped_text("abcdefg", 6),
    "abcdef +1 more chars",
)
check("an empty string is not a special case here either", store.capped_text("", 6), "")
check(
    "a 23 KB line arrives bounded, which is the row all these caps are about",
    store.capped_text("x" * 23000, 240),
    "x" * 240 + " +22760 more chars",
)

print()
print("a scope path, which is the same two fields on a handoff and on a claim")

check(
    "an absolute repo is refused, the field being relative to the root",
    store.scope_fault("--repo", "/etc"),
    "--repo is relative to the root, so it cannot start with /: /etc",
)
check(
    "a repo that climbs out with .. is refused, with the other message",
    store.scope_fault("--repo", "../../etc"),
    "--repo cannot climb out of the root with ..: ../../etc",
)
check(
    "a .. anywhere in the path is refused, not only at the front",
    store.scope_fault("--path", "a/../../b"),
    "--path cannot climb out of the root with ..: a/../../b",
)
# The shape the other two made necessary: a tab is a legal filename character, so the guard passed
# it and every renderer then displayed `/etc`, which is the string the first check above refuses.
# The refusal names the codepoint rather than only the stripped form, and the reason is this exact
# value: `/etc` on its own is a string the typist can see nothing wrong with, so the message read as
# arbitrary and left nothing to act on.
check(
    "a tab in front of an absolute path is refused rather than passed and then stripped",
    store.scope_fault("--repo", "\t/etc"),
    "--repo cannot hold characters a terminal does not show: U+0009. "
    "Without them it reads as '/etc'",
)
check(
    "and the message it comes back with carries no escape of its own",
    "\033" in store.scope_fault("--repo", "x\033[2Ky"),
    False,
)
# A value that is invisible end to end. The stripped form is empty, so the codepoint is the whole of
# what the message has to say - which is what the earlier message could not do at all.
check(
    "a value with nothing visible in it still says what is in it",
    store.scope_fault("--path", "\t\u200b"),
    "--path cannot hold characters a terminal does not show: U+0009, U+200B. "
    "Without them it reads as ''",
)
# Two of the same character is one entry, not two: the message lists what to remove, and repeating a
# codepoint per occurrence makes a long paste unreadable without adding anything.
check(
    "a codepoint is named once however many times it occurs",
    store.scope_fault("--path", "a\tb\tc"),
    "--path cannot hold characters a terminal does not show: U+0009. "
    "Without them it reads as 'abc'",
)
check(
    "a trailing newline is the same shape and the same refusal",
    store.scope_fault("--repo", "..\n"),
    "--repo cannot hold characters a terminal does not show: U+000A. Without them it reads as '..'",
)
# The refusal is wider than "characters a terminal acts on" and that is deliberate for this field.
# U+00A0 renders as a space, so a scope holding one and a scope holding U+0020 are two strings
# nobody can tell apart and the store would hold both. #62 is that problem; this is the half of
# it that can be refused. Written as an escape rather than as the character, because a literal one
# in this file would be a comment nobody could read correctly and a paste nobody could repeat.
check(
    "a space that is not a space is refused too, two scopes nobody can distinguish being the point",
    store.scope_fault("--path", "docs\u00a0shared"),
    "--path cannot hold characters a terminal does not show: U+00A0. "
    "Without them it reads as 'docsshared'",
)
check(
    "an ordinary root-relative repo is fine",
    store.scope_fault("--repo", "plugin/lib"),
    None,
)
check(
    "so is a name that merely contains dots, .. being a whole component or nothing",
    store.scope_fault("--path", "a..b/..bashrc"),
    None,
)

print()
print("a claim another session wrote, rendered")

check(
    "a focus loses the characters a terminal acts on",
    claims.describe_focus({"focus": "HARMLESS\033[2K\033[1;31mURGENT\007"}, 200),
    "HARMLESS[2K[1;31mURGENT",
)
check(
    "a claim with no focus says so rather than rendering an empty line",
    claims.describe_focus({}, 200),
    "(no focus stated)",
)
# Stripped, then capped. The other order gives a row shorter than the cap by however many invisible
# characters the writer put in front of the text, which the reader cannot see and cannot query.
check(
    "the cap counts what the reader sees, not what the writer wrote",
    claims.describe_focus({"focus": "\033[2K\033[2Kabcdef"}, 6),
    "[2K[2K +6 more chars",
)
# #61. `[:cap]` was what this did, and a focus line that stops at the cap with nothing to say so
# reads as the whole of what that session claimed to be doing.
check(
    "and what it cut off is counted rather than dropped",
    claims.describe_focus({"focus": "a" * 300}, 240),
    "a" * 240 + " +60 more chars",
)
check(
    "a focus inside the cap is rendered whole, with nothing appended",
    claims.describe_focus({"focus": "short enough"}, 240),
    "short enough",
)
check(
    "a display name is stripped, being copied out of another session's registry entry",
    claims.describe_name({"session_id": "s1", "name": "peer\033[2Kx"}),
    "peer[2Kx",
)
check(
    "a claim with no name falls back to the id",
    claims.describe_name({"session_id": "s1"}),
    "s1",
)
# Every element. These fields are usually one entry long, so a stripper applied to `values[0]` looks
# right in every case anyone tries by hand.
check(
    "every element of a list field is stripped, not the first one",
    claims.describe_list(["ok", "two\033[2K", "three\007"]),
    ["ok", "two[2K", "three"],
)
check("an empty list field is not a special case", claims.describe_list([]), [])

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

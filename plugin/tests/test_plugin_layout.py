#!/usr/bin/env python3
"""The manifests, and whether the wiring they declare points at anything.

Worth its own file because a plugin whose manifest is malformed or whose handler path is wrong does
not fail loudly - it installs, fires nothing, and looks exactly like a plugin with nothing to say.
Six personal skills sat in the wrong shape for months on this machine for precisely that reason, and
nothing ever said so.
"""

import json
import pathlib
import re
import sys

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
REPO = PLUGIN.parent

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def load(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


print("manifests parse and agree with each other")

marketplace, problem = load(REPO / ".claude-plugin" / "marketplace.json")
check("the marketplace parses", problem, None)
manifest, problem = load(PLUGIN / ".claude-plugin" / "plugin.json")
check("the plugin manifest parses", problem, None)

check("the marketplace lists exactly one plugin", len(marketplace["plugins"]), 1)
listed = marketplace["plugins"][0]
check("and its name matches the manifest", listed["name"], manifest["name"])
# #49. The host caches an install by this version, so a release that does not move it never reaches
# anyone. release-please is what moves it, and only if its config names the file and its manifest
# agrees with what the file says now.
release, problem = load(REPO / "release-please-config.json")
check("the release-please config parses", problem, None)
extra = (release or {}).get("packages", {}).get(".", {}).get("extra-files", [])
check(
    "a release moves the version the host caches by",
    {"type": "json", "path": "plugin/.claude-plugin/plugin.json", "jsonpath": "$.version"} in extra,
    True,
)
released, problem = load(REPO / ".release-please-manifest.json")
check("the release-please manifest parses", problem, None)
check(
    "and the last release it recorded is the version the plugin declares",
    (released or {}).get("."),
    manifest.get("version"),
)
source = (REPO / listed["source"]).resolve()
check("and its source points at the plugin directory", source, PLUGIN)

print("the hooks manifest points at handlers that exist")

hooks, problem = load(PLUGIN / "hooks" / "hooks.json")
check("the hooks manifest parses", problem, None)

events = sorted(hooks["hooks"])
check("the events wired", events, ["SessionEnd", "SessionStart"])

commands = [
    entry["command"]
    for event in hooks["hooks"].values()
    for matcher in event
    for entry in matcher["hooks"]
]
check("every wiring is a command", len(commands), 2)

for command in commands:
    check(
        f"uses the plugin root variable: {command[:40]}...",
        "${CLAUDE_PLUGIN_ROOT}" in command,
        True,
    )
    # The whole point of checking: an unresolvable handler path is silent at runtime.
    referenced = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[^\"']+)", command)
    check("names one path under the plugin root", len(referenced), 1)
    target = PLUGIN / referenced[0].lstrip("/")
    check(f"{referenced[0]} exists", target.is_file(), True)

print("and each handler runs the entrypoint it claims to")

for handler, event in (("session-start.sh", "SessionStart"), ("session-end.sh", "SessionEnd")):
    text = (PLUGIN / "hooks-handlers" / handler).read_text(encoding="utf-8")
    check(f"{handler} passes {event}", f'hook.py" {event}' in text, True)
    # `set -e` in a hook handler turns any future unguarded failure into a failed session, which is
    # rule 2. Read as flags rather than as a substring: the old form here was
    # `("set -e" in text and "set -eu" in text) or "|| exit 0" in text`, and both handlers contain
    # `|| exit 0`, so the right side was always true and the check passed whatever the `set` line
    # said. `set -euo pipefail` went through it green.
    check(
        f"{handler} does not turn on set -e",
        [flags for flags in re.findall(r"^set -(\w+)", text, re.M) if "e" in flags],
        [],
    )
    # And the reason it can afford not to: every call that can fail says so itself.
    guarded = f'hook.py" {event} || exit 0' in text
    check(f"{handler} guards the interpreter it calls", guarded, True)

print("the schemas the code loads are all present")

sys.path.insert(0, str(PLUGIN / "lib"))
import validate  # noqa: E402

for name in ("exchange", "claim", "handoff", "transition"):
    schema, problem = load(validate.SCHEMA_DIR / f"{name}.schema.json")
    check(f"{name}.schema.json parses", problem, None)
    check(f"{name}.schema.json declares its own id", "$id" in schema, True)

print("the command documents only what exists")

command_doc = (PLUGIN / "commands" / "exchange.md").read_text(encoding="utf-8")
check(
    "has frontmatter with a description",
    command_doc.startswith("---\n") and "description:" in command_doc.split("---")[1],
    True,
)

sys.argv = ["exchange"]
import cli  # noqa: E402

parser = cli.build_parser()
subcommands = sorted(
    name for action in parser._subparsers._group_actions for name in action.choices
)
check(
    "the CLI offers what was designed",
    subcommands,
    ["claim", "doctor", "handoff", "init", "migrate", "show"],
)
for name in subcommands:
    # A command the doc does not mention is a command nobody will run.
    check(f"the doc mentions {name}", f"`{name}" in command_doc, True)

# And the same one level down, where the verbs actually are. `handoff` is the only command with its
# own verbs, and the check above passes on the word `handoff` alone however many of them the doc
# has quietly stopped listing - which is how `resolve` could ship documented nowhere but the
# argument hint.
handoff_verbs = sorted(
    name
    for action in parser._subparsers._group_actions
    for verbs in action.choices["handoff"]._subparsers._group_actions
    for name in verbs.choices
)
check(
    "handoff offers the verbs it was designed with",
    handoff_verbs,
    ["accept", "close", "list", "post", "resolve"],
)
for name in handoff_verbs:
    check(f"the doc mentions handoff {name}", f"`handoff {name}" in command_doc, True)

print("and no file in the tree holds a character a reviewer cannot see")

# Three commits on this branch shipped a literal invisible character into source: a ZWJ, a U+3000,
# and a ZWSP with an NBSP beside it. The last two sat inside the checks asserting that those very
# codepoints get stripped, where a literal proves nothing about the code while reading as though it
# does. Nobody catches this class by eye, in review or otherwise, which is the whole argument for
# asserting it instead. Escapes, always.
#
# Every file, with no suffix allowlist. The first cut had one, covering seven extensions, and so
# said nothing about `.gitignore`, `LICENSE`, `NOTICE` or `requirements-ci.txt` - and an invisible
# character in the first of those is a pattern that silently never matches anything, which is worse
# than a comment that reads oddly. The allowlist was the same narrower-than-the-problem shape as
# the bug it was written to stop repeating.
#
# `git ls-files` would be the precise universe and was the second cut. It cannot be: `mutate.py`
# copies the tree without `.git` and runs the whole suite inside that copy, so asking git there
# fails and the baseline dies, which is how CI found it. A walk works in both places, and whether
# a file decodes does the work the allowlist was doing badly.
#
# The three skipped names are `mutate.IGNORE` again, for the same reason it has them, arrived at
# separately rather than shared - importing the sweep harness from a test it sweeps is a worse
# coupling than a repeated list of caches.
illegible = []
scanned = []
for path in sorted(REPO.rglob("*")):
    if not path.is_file() or {".git", "__pycache__", ".ruff_cache"} & set(path.parts):
        continue
    name = str(path.relative_to(REPO))
    try:
        raw = path.read_bytes()
    except OSError as exc:
        illegible.append(f"{name}: not readable, {exc}")
        continue
    # Binary by git's own test, a NUL in the first 8000 bytes, and skipped: a `.DS_Store` appears in
    # any directory Finder has opened, and there is no prose in one for anything to hide in. Not
    # decoding is the test for *everything else*, because a file that fails to decode is where this
    # class hides best: a doc saved from Word or a browser in cp1252 carries NBSP as the bare byte
    # 0xA0, which is not valid utf-8, so skipping undecodable files quietly would let exactly the
    # character this check exists for through while printing ok.
    if b"\0" in raw[:8000]:
        continue
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        illegible.append(f"{name}: not utf-8, {exc}")
        continue
    scanned.append(name)
    # One predicate, the same one `store.printable` is built on: `isprintable` is false for the
    # Other and Separator categories, so control characters, the zero-width formatting ones and
    # NBSP-style spaces are all covered without a list of codepoints here to go out of date.
    # Newline is the only one a file is meant to hold, and a stray carriage return is worth
    # hearing about too. Tab is in deliberately - it is as invisible as the rest and no file here
    # needs one - so the day something arrives that does, a Makefile or a `<<-` heredoc, the
    # exception goes here rather than the check being dropped.
    found = sorted({f"U+{ord(ch):04X}" for ch in text if ch != "\n" and not ch.isprintable()})
    if found:
        illegible.append(f"{name}: {', '.join(found)}")
check("every file reads the way it looks", illegible, [])
# A scan that read nothing reports no problems, which is indistinguishable from a clean tree. It is
# reachable: a walk that resolves nothing, a `REPO` pointing somewhere unexpected. This file is the
# sentinel rather than a floor on the count, being the one file the check is certain exists.
check(
    "and it read the tree rather than nothing",
    str(pathlib.Path(__file__).resolve().relative_to(REPO)) in scanned,
    True,
)

print("the two jobs that run the mutation sweep allow it the same time")


def job_timeout(path, job):
    """`timeout-minutes` for one job, or a sentence saying why there is none.

    Text rather than a YAML parse because the suite is standard-library only and the shape here is
    fixed: two files this repo writes, two-space job keys, four-space job settings.
    """
    block = re.search(rf"\n  {job}:\n(.*?)(?=\n  \w|\Z)", (REPO / path).read_text(), re.S)
    if block is None:
        return f"{path} has no job called {job}"
    found = re.search(r"^    timeout-minutes: (\d+)$", block.group(1), re.M)
    return int(found.group(1)) if found else f"{path}:{job} sets no timeout"


# One number in two files. `ci.yml`'s `mutate` job runs the full sweep whenever a change is wide
# enough - the harness, what a table entry is, which tables exist, `test_cli.py` - so a cap it
# cannot finish under makes a harness change unmergeable while the weekly run stays green, and
# the red then points at a rule that is not broken. `sweep.yml` said "generous next to `ci`'s 15"
# for a fortnight after `ci` went to 45, and nothing objected, which is what a number restated in
# a second file does.
narrowed = job_timeout(".github/workflows/ci.yml", "mutate")
full = job_timeout(".github/workflows/sweep.yml", "sweep")
# First, because the comparison below passes on two identical sentences. The default is 360 minutes
# and a hang bills every one of them, so a job here having no cap is its own finding.
check(
    "both of them set one at all, the default being six hours of billed hang",
    [cap for cap in (narrowed, full) if not isinstance(cap, int)],
    [],
)
# Held against each other rather than against a literal, which would be the same number written a
# third time and would have to be edited whenever either moves.
check(
    "and the narrowed sweep allows itself exactly what the full one does",
    (narrowed, full),
    (full, full),
)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

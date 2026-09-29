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

print("and no file in the tree carries a character a reviewer cannot see")

# Three commits on this branch shipped a literal invisible character into source: a ZWJ, a U+3000,
# and a ZWSP with an NBSP beside it. The last two sat inside the checks asserting that those very
# codepoints get stripped, where a literal proves nothing about the code while reading as though it
# does. Nobody catches this class by eye, in review or otherwise, which is the whole argument for
# asserting it instead. Escapes, always.
TEXT_SUFFIXES = (".py", ".md", ".json", ".sh", ".yml", ".yaml", ".toml")
illegible = []
for path in sorted(REPO.rglob("*")):
    if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
        continue
    if {".git", "__pycache__"} & set(path.parts):
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        illegible.append(f"{path.relative_to(REPO)}: not readable as utf-8, {exc}")
        continue
    # One predicate, the same one `store.printable` is built on: `isprintable` is false for the
    # Other and Separator categories, so control characters, the zero-width formatting ones and
    # NBSP-style spaces are all covered without a list of codepoints here to go out of date.
    # Newline is the only one a file is meant to hold, and a stray carriage return is worth
    # hearing about too.
    found = sorted({f"U+{ord(ch):04X}" for ch in text if ch != "\n" and not ch.isprintable()})
    if found:
        illegible.append(f"{path.relative_to(REPO)}: {', '.join(found)}")
check("every file reads the way it looks", illegible, [])

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

#!/usr/bin/env python3
"""Root resolution, on synthetic trees rather than on this machine's layout.

Every tree below is built in a tmpdir, so the checks say what the rules do rather than what one
laptop happens to look like. The two real-world cases the plan names are asserted as shapes: a repo
inside an area resolves to the area, and a directory of areas is refused.

Discipline carried from the parser fix: a check has to be able to fail. Where a rule is asserted,
the opposite arrangement is asserted too, because a test that passes identically whether the rule
is implemented or not is asserting nothing. That is how a dead parser read as a quiet day for ten
days.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import exchange_root  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def tree(base, *, areas=(), repos_in=None, marker_at=None, claude_at=()):
    """Build a synthetic workspace. Returns the base path."""
    base = pathlib.Path(base).resolve()
    for area in areas:
        (base / area).mkdir(parents=True, exist_ok=True)
        (base / area / "CLAUDE.md").write_text("area\n")
    for d in claude_at:
        (base / d).mkdir(parents=True, exist_ok=True)
        (base / d / "CLAUDE.md").write_text("marked\n")
    if repos_in:
        for repo in repos_in:
            (base / repo / ".git").mkdir(parents=True, exist_ok=True)
            (base / repo / "CLAUDE.md").write_text("repo\n")
    if marker_at:
        (base / marker_at / ".claude").mkdir(parents=True, exist_ok=True)
        (base / marker_at / ".claude" / "exchange.json").write_text(json.dumps({"name": "t"}))
    return base


print("precedence")

with tempfile.TemporaryDirectory() as tmp:
    base = tree(tmp, areas=["work"], repos_in=["work/repo"], marker_at="work")
    r = exchange_root.resolve(base / "work/repo")
    check("marker on an ancestor resolves to it", (r.root, r.rule), (base / "work", "marker"))

    # Nearest wins. Mark the repo too and the same cwd must now stop there.
    tree(tmp, marker_at="work/repo")
    r = exchange_root.resolve(base / "work/repo")
    check("nested roots: innermost wins", (r.root, r.rule), (base / "work/repo", "marker"))

with tempfile.TemporaryDirectory() as tmp:
    base = tree(tmp, areas=["work"], repos_in=["work/repo"])
    r = exchange_root.resolve(base / "work/repo")
    check("no marker anywhere is a silent no-op", (r.root, r.rule, r.problem),
          (None, "unmarked", None))

    # The override needs no marker at all - that is the point of it.
    r = exchange_root.resolve(base / "work/repo", {"CC_EXCHANGE_ROOT": str(base / "work")})
    check("override beats the walk, with no marker present", (r.root, r.rule),
          (base / "work", "override"))

    # And it wins even when a marker would have resolved.
    tree(tmp, marker_at="work/repo")
    r = exchange_root.resolve(base / "work/repo", {"CC_EXCHANGE_ROOT": str(base / "work")})
    check("override beats a marker", r.root, base / "work")

    # Set-and-wrong is a mistake, not a quiet day. Unset is rule 3; this is not.
    r = exchange_root.resolve(base / "work/repo", {"CC_EXCHANGE_ROOT": str(base / "nope")})
    check("override pointing nowhere is loud", (r.root, r.rule, r.problem is not None),
          (None, "override-invalid", True))
    r = exchange_root.resolve(base / "work/repo", {"CC_EXCHANGE_ROOT": "   "})
    check("blank override falls through rather than erroring", r.rule, "marker")

print("a marker that exists and does not parse is not 'no exchange here'")

with tempfile.TemporaryDirectory() as tmp:
    base = tree(tmp, areas=["work"], marker_at="work")
    config, problem = exchange_root.read_marker(base / "work")
    check("valid marker reads", (config, problem), ({"name": "t"}, None))

    (base / "work/.claude/exchange.json").write_text("{not json")
    config, problem = exchange_root.read_marker(base / "work")
    check("unparseable marker reports why", (config, problem is not None), (None, True))

    (base / "work/.claude/exchange.json").write_text('["a list"]')
    config, problem = exchange_root.read_marker(base / "work")
    check("marker must be an object", (config, problem is not None), (None, True))

print("where init would mark")

with tempfile.TemporaryDirectory() as tmp:
    # A repo inside an area inside a directory of areas: the shape of the real workspace.
    base = tree(tmp, areas=["projects/work", "projects/personal", "projects/public"],
                repos_in=["projects/work/repo", "projects/personal/dotfiles"])
    (base / "projects/CLAUDE.md").write_text("areas\n")
    (base / "CLAUDE.md").write_text("root\n")

    default, candidates = exchange_root.init_candidates(base / "projects/work/repo")
    check("defaults to the area, not the repo", default, base / "projects/work")
    check("the repo itself is never a candidate", base / "projects/work/repo" in candidates, False)
    check("the directory of areas is offered but not chosen",
          (base / "projects" in candidates, default == base / "projects"), (True, False))

    default, _ = exchange_root.init_candidates(base / "projects/personal/dotfiles")
    check("same rule from a different area", default, base / "projects/personal")

    # Break it: if the sibling areas stop looking like areas, `projects` stops being refused.
    # Without this the merge-point check could be a no-op and every assertion above would still pass.
    for area in ("work", "personal", "public"):
        (base / "projects" / area / "CLAUDE.md").unlink()
    default, _ = exchange_root.init_candidates(base / "projects/work/repo")
    check("with no sibling areas, the container is no longer refused", default, base / "projects")

with tempfile.TemporaryDirectory() as tmp:
    # Areas that are themselves repos are a directory of repos, which is a legitimate root.
    base = tree(tmp, repos_in=["mono/a", "mono/b"], claude_at=["mono"])
    default, _ = exchange_root.init_candidates(base / "mono/a")
    check("a directory of repos is a legitimate root", default, base / "mono")

with tempfile.TemporaryDirectory() as tmp:
    base = tree(tmp, repos_in=["orphan"])
    default, candidates = exchange_root.init_candidates(base / "orphan")
    check("nothing to mark returns None rather than guessing", (default, candidates), (None, []))

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

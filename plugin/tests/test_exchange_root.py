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
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import exchange_root

# Every check here passes the environment it means to test, except where the rule under test is the
# fallback to the real one. `CC_EXCHANGE_ROOT` beats every fixture below, and it is a documented
# per-pane override that anyone using this plugin may well have set, so leaving it in place means
# the suite fails for five unrelated reasons on the machines most likely to be running it.
os.environ.pop("CC_EXCHANGE_ROOT", None)

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
    check(
        "no marker anywhere is a silent no-op",
        (r.root, r.rule, r.problem),
        (None, "unmarked", None),
    )

    # The override needs no marker at all - that is the point of it.
    r = exchange_root.resolve(base / "work/repo", {"CC_EXCHANGE_ROOT": str(base / "work")})
    check(
        "override beats the walk, with no marker present",
        (r.root, r.rule),
        (base / "work", "override"),
    )

    # And it wins even when a marker would have resolved.
    tree(tmp, marker_at="work/repo")
    r = exchange_root.resolve(base / "work/repo", {"CC_EXCHANGE_ROOT": str(base / "work")})
    check("override beats a marker", r.root, base / "work")

    # Set-and-wrong is a mistake, not a quiet day. Unset is rule 3; this is not.
    r = exchange_root.resolve(base / "work/repo", {"CC_EXCHANGE_ROOT": str(base / "nope")})
    check(
        "override pointing nowhere is loud",
        (r.root, r.rule, r.problem is not None),
        (None, "override-invalid", True),
    )
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
    # A repo inside an area inside a directory of areas. Named for the shape and nothing else:
    # this is the layout the resolution rules have to handle, not a layout anyone has to adopt.
    base = tree(
        tmp,
        areas=["container/alpha", "container/beta", "container/gamma"],
        repos_in=["container/alpha/repo", "container/beta/other-repo"],
    )
    (base / "container/CLAUDE.md").write_text("areas\n")
    (base / "CLAUDE.md").write_text("root\n")

    default, candidates = exchange_root.init_candidates(base / "container/alpha/repo")
    check("defaults to the area, not the repo", default, base / "container/alpha")
    check(
        "the repo itself is never a candidate",
        base / "container/alpha/repo" in candidates,
        False,
    )
    check(
        "the directory of areas is offered but not chosen",
        (base / "container" in candidates, default == base / "container"),
        (True, False),
    )

    default, _ = exchange_root.init_candidates(base / "container/beta/other-repo")
    check("same rule from a different area", default, base / "container/beta")

    # Break it: if the sibling areas stop looking like areas, `container` stops being refused.
    # Without this the merge-point check could be a no-op and every assertion above would still
    # pass.
    for area in ("alpha", "beta", "gamma"):
        (base / "container" / area / "CLAUDE.md").unlink()
    default, _ = exchange_root.init_candidates(base / "container/alpha/repo")
    check("with no sibling areas, the container is no longer refused", default, base / "container")

with tempfile.TemporaryDirectory() as tmp:
    # Areas that are themselves repos are a directory of repos, which is a legitimate root.
    base = tree(tmp, repos_in=["mono/a", "mono/b"], claude_at=["mono"])
    default, _ = exchange_root.init_candidates(base / "mono/a")
    check("a directory of repos is a legitimate root", default, base / "mono")

with tempfile.TemporaryDirectory() as tmp:
    base = tree(tmp, repos_in=["orphan"])
    default, candidates = exchange_root.init_candidates(base / "orphan")
    check("nothing to mark returns None rather than guessing", (default, candidates), (None, []))

print("init from an area directory, which is the documented way to launch")

with tempfile.TemporaryDirectory() as tmp:
    # "Launch Claude from the relevant workspace root" is what the workspace's own CLAUDE.md says to
    # do, and it was the one place the default came back empty: with no enclosing repo the ceiling
    # was cwd, so cwd was excluded by the strictness that exists to stop a repo-scoped exchange.
    base = tree(
        tmp,
        areas=["container/alpha", "container/beta", "container/gamma"],
        repos_in=["container/alpha/repo", "container/alpha/other-repo"],
    )
    (base / "container/CLAUDE.md").write_text("areas\n")

    # Stated as a precondition rather than assumed. This is the only block whose right answers need
    # `git_root` to come back None, so a `.git` above the tempdir - where a tempdir lands when
    # `TMPDIR` points inside a checkout - quietly changes three answers below. Asserted, so that
    # environment fails as a named assumption instead of as three mysterious wrong roots.
    check(
        "no enclosing repo above the fixture",
        exchange_root.git_root(base / "container/alpha"),
        None,
    )

    default, candidates = exchange_root.init_candidates(base / "container/alpha")
    check("an area directory marks itself", default, base / "container/alpha")
    check("and is offered, not just chosen", base / "container/alpha" in candidates, True)
    # The directory of areas above it is refused on its own merits. Asserted directly rather than as
    # `default != container`, which is implied by the check above and also passes when default is
    # None: it was written that way first and stubbing the merge-point rule out left it green.
    check(
        "the directory of areas above it is a merge point",
        exchange_root.is_merge_point(base / "container"),
        True,
    )
    # And with the nearer answer taken away, the refusal is what decides the outcome: nothing is
    # offered below `container`, `container` is offered and still not chosen. Three areas in the
    # fixture rather than two, so dropping alpha's marker leaves the container over the threshold -
    # with two it fell under it, and the check passed for the wrong reason.
    (base / "container/alpha/CLAUDE.md").unlink()
    default, candidates = exchange_root.init_candidates(base / "container/alpha")
    check(
        "so with nothing nearer, init has no answer rather than falling back to it",
        (default, base / "container" in candidates),
        (None, True),
    )
    (base / "container/alpha/CLAUDE.md").write_text("area\n")

    # Considered, not taken: cwd still has to carry a `CLAUDE.md`. Without this, marking whatever
    # directory the shell happened to be in would pass every check above.
    (base / "container/alpha/scratch").mkdir()
    default, candidates = exchange_root.init_candidates(base / "container/alpha/scratch")
    check(
        "a cwd with no CLAUDE.md is not a candidate",
        base / "container/alpha/scratch" in candidates,
        False,
    )
    check("and the walk still answers the area above it", default, base / "container/alpha")

print("the merge-point shape is read from the children alone, .git at the top changing nothing")

with tempfile.TemporaryDirectory() as tmp:
    # #33 asked for a git root to be exempted, on the grounds that a repo *storing* `CLAUDE.md`
    # files has the same shape as a directory of areas. It was implemented and reverted: exempting
    # git roots also exempted a git root holding two real areas, so `init` marked it with no
    # `--force` and each area saw the other's claims. Both readings of the shape are asserted below,
    # because the point is that this function cannot distinguish them and does not try.
    base = pathlib.Path(tmp).resolve()
    (base / "stores" / ".git").mkdir(parents=True)
    (base / "stores" / "CLAUDE.md").write_text("repo\n")
    for stored in ("stored-a", "stored-b"):
        (base / "stores" / stored).mkdir()
        (base / "stores" / stored / "CLAUDE.md").write_text("stored copy\n")

    check(
        "a repo storing two CLAUDE.md files still reads as a merge point",
        exchange_root.is_merge_point(base / "stores"),
        True,
    )

    # The arrangement the refusal exists for, wearing the same `.git`. If a git-root exemption comes
    # back, this is the check that fails, and it is the one worth failing: the two trees differ only
    # in whether the children hold repos, which is not what an exemption looks at.
    (base / "areas" / ".git").mkdir(parents=True)
    (base / "areas" / "CLAUDE.md").write_text("repo\n")
    for area in ("area-a", "area-b"):
        (base / "areas" / area / "repo" / ".git").mkdir(parents=True)
        (base / "areas" / area / "CLAUDE.md").write_text("area\n")
    check(
        "and a repo holding two real areas is one too, which is why there is no exemption",
        exchange_root.is_merge_point(base / "areas"),
        True,
    )

    # Break it in the other direction: one stored child is not two, so a `return True` here would
    # pass both checks above and assert nothing about the threshold.
    (base / "stores" / "stored-b" / "CLAUDE.md").unlink()
    check(
        "one stored child is not a merge point, .git or no .git",
        exchange_root.is_merge_point(base / "stores"),
        False,
    )

print("the rules a sweep found nothing asserting")

# Every check below exists because a mutation of the rule it names survived. `exchange_root` got its
# table after four other modules had one, and ten of the twenty-two rules it held then turned out to
# be asserted by nothing: good coverage of the answers it gives, almost none of the reasons.

with tempfile.TemporaryDirectory() as tmp:
    base = tree(tmp, areas=["work"], marker_at="work")

    # An override is resolved, not just expanded. Every caller treats the root as a key - claims are
    # written under it and compared by it - so the same directory reached by two spellings has to be
    # one root and not two.
    detour = base / "work" / ".." / "work"
    r = exchange_root.resolve(base / "work", {"CC_EXCHANGE_ROOT": str(detour)})
    check("an override is resolved, so one directory is one root", r.root, base / "work")

    # `cwd-invalid` had no check at all, which meant a cwd that does not exist walked its parents as
    # though it did. That is not academic: the payload's `cwd` is whatever Claude Code sent, and a
    # deleted directory resolving to its parent's root is a session claiming to be somewhere else.
    r = exchange_root.resolve(base / "work" / "gone")
    check(
        "a cwd that is not a directory says so rather than walking",
        (r.root, r.rule, r.problem is not None),
        (None, "cwd-invalid", True),
    )

with tempfile.TemporaryDirectory() as tmp:
    # A marker that is a directory. `mkdir -p .claude/exchange.json` is one keystroke from the real
    # thing, and `exists()` in place of `is_file()` would make it mark the tree.
    base = pathlib.Path(tmp).resolve()
    (base / "work" / ".claude" / "exchange.json").mkdir(parents=True)
    r = exchange_root.resolve(base / "work")
    check("a directory named like the marker marks nothing", r.rule, "unmarked")

    # And the read side of the same thing: a root with no marker at all is a problem, because every
    # caller of `read_marker` has already decided there is a root and is asking what it says.
    config, problem = exchange_root.read_marker(base)
    check(
        "a missing marker is a problem, not empty config",
        (config, problem is not None),
        (None, True),
    )

with tempfile.TemporaryDirectory() as tmp:
    # `.git` is a directory in a normal clone and a *file* in a worktree or a submodule. Both of the
    # worktrees this plugin was built in are the second kind, so `is_dir()` here would have made the
    # tool wrong in exactly the checkout it was written in and right everywhere it was tested.
    base = pathlib.Path(tmp).resolve()
    (base / "wt" / "sub").mkdir(parents=True)
    (base / "wt" / ".git").write_text("gitdir: /somewhere/.git/worktrees/wt\n")
    check(
        "a worktree is a repo, .git being a file",
        exchange_root.git_root(base / "wt" / "sub"),
        base / "wt",
    )

with tempfile.TemporaryDirectory() as tmp:
    # The repo is the ceiling, and cwd is not. `init` run from a subdirectory has to answer what it
    # answers from the repo root, or the suggestion depends on which directory you were in.
    base = tree(
        tmp,
        areas=["container/alpha", "container/beta"],
        repos_in=["container/alpha/repo"],
    )
    (base / "container/CLAUDE.md").write_text("areas\n")
    (base / "CLAUDE.md").write_text("root\n")
    (base / "container/alpha/repo/deep/nested").mkdir(parents=True)

    default, candidates = exchange_root.init_candidates(base / "container/alpha/repo/deep/nested")
    check("init from deep inside a repo answers the same", default, base / "container/alpha")
    check(
        "and the repo is still not a candidate", base / "container/alpha/repo" in candidates, False
    )

    # Home is excluded however it is spelled. Asserted by setting HOME rather than by trusting this
    # machine's: on a laptop with a `~/CLAUDE.md` - which is the normal case for anyone using Claude
    # Code - marking home would give every session on the machine sight of every other one.
    was = os.environ.get("HOME")
    try:
        os.environ["HOME"] = str(base / "container")
        _, candidates = exchange_root.init_candidates(base / "container/alpha/repo")
        check("home is never a candidate", base / "container" in candidates, False)
    finally:
        if was is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = was

with tempfile.TemporaryDirectory() as tmp:
    # The nearest candidate being the merge point is the arrangement that matters, and the one the
    # checks above did not have: with the merge point second in the list, taking the nearest
    # gives the right answer by accident and the skip could have been missing entirely.
    base = tree(
        tmp, areas=["hub/area-one", "hub/area-two"], repos_in=["hub/repo"], claude_at=["hub"]
    )
    (base / "CLAUDE.md").write_text("above\n")

    default, candidates = exchange_root.init_candidates(base / "hub/repo")
    check("the nearest candidate is skipped when it is a merge point", default, base)
    check("and it is still offered", base / "hub" in candidates, True)

    # Two is the threshold, and both sides of it are asserted here. This was caught only by
    # `test_cli.py` before, which is the module's own rule being held up by another module's test.
    check("two sibling areas is a merge point", exchange_root.is_merge_point(base / "hub"), True)
    (base / "hub/area-two/CLAUDE.md").unlink()
    check("one is not", exchange_root.is_merge_point(base / "hub"), False)

    # A file rather than a directory. `iterdir` raises `NotADirectoryError`, and this is called
    # while deciding what to suggest, so raising turns a cosmetic oddity into a failed `init`.
    #
    # Caught rather than called bare, because the rule includes "and not an exception either" and a
    # bare call cannot say that: the expression raises before `check` is entered, so the name never
    # prints, `failures` is never appended, and the nonzero exit comes from the traceback instead of
    # from the assertion. The sweep scores that as a catch, off the crash rather than off the check,
    # which is the thing this file exists to stop being satisfied on paper.
    try:
        listed = exchange_root.is_merge_point(base / "CLAUDE.md")
    except Exception as exc:
        listed = f"raised {type(exc).__name__}"
    check("something that cannot be listed is not a merge point", listed, False)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

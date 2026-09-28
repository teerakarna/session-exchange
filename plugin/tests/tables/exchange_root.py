"""The rules `exchange_root.py` has to keep, one broken way each."""

from .shape import Mutation

# Root resolution, which the plan calls the test that must never regress: every other module is
# handed a root and does not look for one, so a wrong answer here is the one bug that can show a
# session in one area the presence and handoffs of another. Ten of the twenty-two rules this table
# held when it was written had nothing asserting them, which is the arithmetic that made it worth
# writing rather than a suspicion about it. It has grown since, and the twenty-two stays as the
# count that figure was measured against rather than re-pointed at whatever the table holds today.
MUTATIONS = [
    Mutation(
        module="exchange_root",
        rule="the override is consulted before the walk, not after",
        old="    if override:",
        new="    if False:",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="whitespace in the override means unset, not a directory named with spaces",
        old='    override = (environ.get(OVERRIDE_VAR) or "").strip()',
        new='    override = environ.get(OVERRIDE_VAR) or ""',
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="an override that is not a directory resolves to no root",
        old="        if not path.is_dir():",
        new="        if False:",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="and says which variable it was and what it was set to",
        old='                f"{OVERRIDE_VAR} is set to {override!r}, which is not a directory.",',
        new='                "the exchange root is not a directory.",',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="exchange_root",
        rule="an override is resolved, so every root the plugin hands out is absolute and real",
        old='        return Resolution(path.resolve(), "override")',
        new='        return Resolution(path, "override")',
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="a cwd that is not a directory is a reported problem, not an unmarked walk",
        old="    if not start.is_dir():",
        new="    if False:",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="the walk goes up, so the nearest marker wins and nested roots do not leak",
        old="    for candidate in (start.resolve(), *start.resolve().parents):",
        new="    for candidate in reversed([start.resolve(), *start.resolve().parents]):",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="the walk starts at cwd, so a marked directory resolves to itself",
        old="    for candidate in (start.resolve(), *start.resolve().parents):",
        new="    for candidate in start.resolve().parents:",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="the marker has to be a file, so a directory of that name marks nothing",
        old="        if (candidate / MARKER).is_file():",
        new="        if (candidate / MARKER).exists():",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="nothing found is no root, not this directory by default",
        old='    return Resolution(None, "unmarked")',
        new='    return Resolution(pathlib.Path(cwd), "unmarked")',
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="a marker that is not there is a problem, not empty config",
        old='        return None, f"{path} does not exist."',
        new="        return {}, None",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="a marker that does not parse is a problem, not empty config",
        old='        return None, f"{path} is not valid JSON: {exc}."',
        new="        return {}, None",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="a marker holding something other than an object is a problem too",
        old="    if not isinstance(config, dict):",
        new="    if False:",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="a worktree is a repo, where .git is a file rather than a directory",
        old='        if (candidate / ".git").exists():',
        new='        if (candidate / ".git").is_dir():',
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="init marks strictly above the repo: a repo-scoped exchange coordinates nothing",
        old="    searched = [start, *start.parents] if repo is None else list(repo.parents)",
        new="    searched = [start, *start.parents]",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="the ceiling is the repo, not cwd, so init from a subdirectory answers the same",
        old="    searched = [start, *start.parents] if repo is None else list(repo.parents)",
        new="    searched = [start, *start.parents] if repo is None else list(start.parents)",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        # The two branches want a mutation each. They were one line reading `ceiling = repo if repo
        # else start`, and the no-repo half was wrong for as long as it existed: cwd was excluded by
        # the strictness that exists to skip the git root, so `init` in an area directory - which is
        # the documented launch point - offered nothing and refused the merge point above it.
        rule="with no enclosing repo, cwd is a candidate: an area directory can mark itself",
        old="    searched = [start, *start.parents] if repo is None else list(repo.parents)",
        new="    searched = list(start.parents) if repo is None else list(repo.parents)",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="home is never a candidate, however many CLAUDE.md files are above it",
        old=('    candidates = [d for d in searched if (d / "CLAUDE.md").is_file() and d != home]'),
        new='    candidates = [d for d in searched if (d / "CLAUDE.md").is_file()]',
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="a candidate has to carry a CLAUDE.md, cwd included",
        old=('    candidates = [d for d in searched if (d / "CLAUDE.md").is_file() and d != home]'),
        new="    candidates = [d for d in searched if d != home]",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="the default skips a merge point rather than taking the nearest candidate",
        old="    default = next((d for d in candidates if not is_merge_point(d)), None)",
        new="    default = candidates[0] if candidates else None",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        # Skipped for the default and still offered are two rules, not one, and the second had no
        # mutation: filtering merge points out of `candidates` leaves `default` identical,
        # so every check on the default passes and the only thing lost is a human's ability to
        # override the suggestion with the answer the tool declined to pick.
        rule="a merge point is still offered, so the suggestion can be overridden",
        old=('    candidates = [d for d in searched if (d / "CLAUDE.md").is_file() and d != home]'),
        new=(
            "    candidates = [\n"
            "        d for d in searched\n"
            '        if (d / "CLAUDE.md").is_file() and d != home and not is_merge_point(d)\n'
            "    ]"
        ),
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="two sibling areas is already a merge point, not three",
        old="    return len(areas) >= 2",
        new="    return len(areas) >= 3",
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="children that are repos do not make their parent a merge point",
        old=(
            "    areas = [c for c in children "
            'if (c / "CLAUDE.md").is_file() and not (c / ".git").exists()]'
        ),
        new='    areas = [c for c in children if (c / "CLAUDE.md").is_file()]',
        caught_by="test_exchange_root.py",
    ),
    Mutation(
        module="exchange_root",
        rule="a path that cannot be listed is not a merge point, and is not an exception either",
        old="    except OSError:\n        return False",
        new="    except OSError:\n        raise",
        caught_by="test_exchange_root.py",
    ),
]

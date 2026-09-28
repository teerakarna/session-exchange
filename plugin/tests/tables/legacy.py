"""The rules `legacy.py` has to keep, one broken way each."""

from .shape import Mutation

# Written before `test_legacy.py` existed, on the assumption that the end-to-end files already held
# most of this module up: `test_hook.py` has a whole `wire_legacy` fixture and `test_cli.py` drives
# `doctor` through it. Five of the first nineteen were caught by something other than the file named
# here, which the harness scores as a survivor precisely so a guess like that cannot pass quietly,
# and in all five the only objection came from the new unit file. What the end-to-end fixtures pin
# down is the rendered warning; those five are the cases the fixtures never produce.
#
# The most instructive is `double_fire`. In `test_cli.py` the legacy script is on disk *and* wired
# in every fixture that has one, so reading `on_disk` there gives the same answer as `wired` -
# two inputs that agree cannot say which one was read. The distinction is the entire point of the
# field: an unwired script is inert, a wired one doubles the SessionStart injection.
#
# The last five came with the scope split, and the same shape produced the bug they cover: with
# the only wired fixture being the machine-wide one, `wired` and "wired under this root" agreed, and
# `double_fire` off `bool(wired)` looked right for the same reason - until the first real migration,
# where the machine-wide wiring rendered another root's rows and the warning called it a doubling.
# Two of the five only fail against `under` called directly, which is why that helper is public.
MUTATIONS = [
    Mutation(
        module="legacy",
        # The module's first documented rule, and the one a generalised tool has to keep: two of the
        # scripts carry one environment's project prefix, so matching literals would either ship
        # another workspace's name inside the plugin or stop matching the moment one is renamed.
        rule="detection is by shape, not by literal name",
        old="    return any(fnmatch.fnmatch(name, pattern) for pattern in LEGACY_GLOBS)",
        new="    return any(name == pattern for pattern in LEGACY_GLOBS)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        rule="one glob matching is enough, since the scripts are four unrelated shapes",
        old="    return any(fnmatch.fnmatch(name, pattern) for pattern in LEGACY_GLOBS)",
        new="    return all(fnmatch.fnmatch(name, pattern) for pattern in LEGACY_GLOBS)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        rule="a hooks directory that is not there is empty, not an exception",
        old="    if not hooks_dir.is_dir():",
        new="    if False:",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="a legacy script has to be a file, not a directory named like one",
        old=(
            "    return sorted(p for p in hooks_dir.iterdir() "
            "if p.is_file() and looks_legacy(p.name))"
        ),
        new="    return sorted(p for p in hooks_dir.iterdir() if looks_legacy(p.name))",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="the user settings file is searched, because that is where the old pair was wired",
        old=(
            "    found = [user_settings] "
            "if user_settings and pathlib.Path(user_settings).is_file() else []"
        ),
        new="    found = []",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        rule="a root's own settings.local.json is searched",
        old='        root / ".claude" / "settings.local.json",',
        new='        root / ".claude" / "never-a-real-file.json",',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        # The per-repo wiring being migrated away from lives exactly one level down, so losing this
        # is losing the common case while the user-settings case goes on passing.
        rule="and so is each repo one level under it",
        old='        *sorted(root.glob("*/.claude/settings.local.json")),',
        new='        *sorted(root.glob(".claude/settings.local.json")),',
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="a string anywhere in settings is a string that was read",
        old="    if isinstance(obj, str):\n        yield obj",
        new='    if isinstance(obj, str):\n        yield ""',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        rule="the walk goes into dicts, which is where every documented wiring is",
        old="        for value in obj.values():",
        new="        for value in []:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        rule="and into lists, which is the shape of a hooks array",
        old="        for value in obj:\n            yield from _strings(value)",
        new="        for value in []:\n            yield from _strings(value)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        rule="a settings file that is not there is not a problem worth reporting",
        old="        except FileNotFoundError:\n            continue",
        new=(
            "        except FileNotFoundError:\n"
            '            problems.append(f"{path} is missing")\n'
            "            continue"
        ),
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="a settings file that cannot be read is reported as unknown, not as clean",
        old=(
            '            problems.append(f"{path} could not be read, '
            'so wiring there is unknown: {exc}")'
        ),
        new="            pass",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="a command in quotes is still split into tokens",
        old='            for token in text.replace(\'"\', " ").replace("\'", " ").split():',
        new="            for token in text.split():",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="a token is reduced to its basename, or a path never matches a glob",
        old="                name = pathlib.PurePath(token).name",
        new="                name = token",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        # The privacy rule, and the only one here whose failure is a diagnostic quoting another
        # environment's arguments back at a log to establish a fact the basename already makes.
        rule="only the script's name is reported, never the command string it sat in",
        old="                    names.add(name)",
        new="                    names.add(text)",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="something that is not a legacy script is not a wiring",
        old="                if looks_legacy(name):",
        new="                if True:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="legacy",
        rule="what is on disk is reported",
        old='        "on_disk": on_disk,',
        new='        "on_disk": [],',
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        # The distinction the whole guard turns on: an unwired script on disk is inert, a wired one
        # fires alongside the plugin and doubles the SessionStart injection.
        rule="a doubled fire is a wiring, not a file on disk",
        old='        "double_fire": bool(scoped),',
        new='        "double_fire": bool(on_disk),',
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        # The fault a wiring is depends on where it lives, and before the split both arms read as
        # a doubled fire. Which meant a session handed another root's presence was told its own had
        # been rendered twice - the one thing root resolution exists to prevent, described as
        # something else. Observed on the first real migration, not imagined.
        rule="a wiring outside this root is not this root's rendering doubled",
        old=(
            "    scoped = [(path, name) for path, name in wired "
            "if under(root, path)] if root else []"
        ),
        new="    scoped = list(wired)",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="and a wiring inside it is",
        old=(
            "    scoped = [(path, name) for path, name in wired "
            "if under(root, path)] if root else []"
        ),
        new="    scoped = []",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        # `under` is compared against a root that arrives resolved and paths globbed from it, so the
        # two sides agree in the ordinary case and neither of these shows up end to end. Unresolved,
        # both answer no, and a no here puts a root's own wiring in the machine-wide bucket.
        rule="a path is resolved before it is compared, so a symlinked route is the same file",
        old="    return pathlib.Path(path).resolve().is_relative_to(pathlib.Path(root).resolve())",
        new="    return pathlib.Path(path).is_relative_to(pathlib.Path(root).resolve())",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="and so is the root, so a symlinked root is still that root",
        old="    return pathlib.Path(path).resolve().is_relative_to(pathlib.Path(root).resolve())",
        new="    return pathlib.Path(path).resolve().is_relative_to(pathlib.Path(root))",
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        # The other half of the same split. Reported as machine-wide too, this root's own wiring
        # produces a warning about some other root that does not exist, which sends whoever reads it
        # to `doctor` in an environment that has nothing wrong with it.
        rule="a wiring that belongs to this root is not also machine-wide",
        old='        "machine_wide": [pair for pair in wired if pair not in scoped],',
        new='        "machine_wide": list(wired),',
        caught_by="test_legacy.py",
    ),
    Mutation(
        module="legacy",
        rule="no root means no settings to search, rather than a crash",
        old=(
            "    wired, problems = wirings(settings_files(root, user_settings)) "
            "if root else ([], [])"
        ),
        new="    wired, problems = wirings(settings_files(root, user_settings))",
        caught_by="test_legacy.py",
    ),
]

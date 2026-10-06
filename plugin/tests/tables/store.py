"""The rules `store.py` has to keep, one broken way each."""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="store",
        rule="an id that cannot be a filename is refused rather than sanitised",
        old="    return value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None",
        new="    return value",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="fullmatch, because Python's $ also matches before a trailing newline",
        old="    return value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None",
        new="    return value if isinstance(value, str) and SAFE_ID.match(value) else None",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="an invalid object never reaches disk",
        old='            return None, f"refusing to write {path}: " + "; ".join(problems)',
        new="            pass",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        # The mutation is a writer that replaces, which is what `post` used to call under an
        # `exists()` check. `os.link` is one syscall that either creates the name or fails, so there
        # is no window between the check and the write for a second writer to fit into.
        rule="create_json creates or fails, and never replaces",
        old="        os.link(tmp, path)",
        new="        os.replace(tmp, path)",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        # The mutation is what this was first. An id may contain a dot, so an id of `note.json`
        # put a moves directory at `handoffs/note.json` - exactly where a record of the id `note`
        # goes - and `read_all`'s glob then tried to parse the directory as a record, for good.
        # The suffix cannot be a record's name, so the two namespaces cannot overlap whatever the
        # id is, which beats a rule that ids must not end in `.json` because nothing has to
        # remember it.
        rule="a handoff's moves live under a name no record could have",
        old='    return handoffs_dir(root) / f"{handoff_id}.d"',
        new="    return handoffs_dir(root) / handoff_id",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="store",
        rule="a file that exists and does not parse is never reported as absent",
        old=(
            "    except (OSError, ValueError) as exc:\n"
            '        return None, f"{name} could not be read: {exc}"'
        ),
        new="    except (OSError, ValueError):\n        return None, None",
        caught_by="test_store_claims.py",
    ),
    # #47. `if True` rather than deleting the comprehension, so what breaks is the predicate and not
    # the shape of the function: a mutation that also changes the return type is caught by anything
    # that calls it, which would score a catch this rule has not earned.
    Mutation(
        module="store",
        rule="text another session wrote loses the characters a terminal acts on",
        old='    return "".join(ch for ch in value if ch.isprintable())',
        new='    return "".join(ch for ch in value if True)',
        caught_by="test_store_claims.py",
    ),
    # The other direction of the same predicate, and the reason it is worth a second entry: the one
    # above is satisfied by any rule that drops an escape, including a narrowing to ASCII, which
    # would silently take every accented, CJK and Thai character in the store with it. The check it
    # names asserted only ASCII prose, so the narrowing was available and nothing would have gone
    # red.
    Mutation(
        module="store",
        rule="and keeps the ones it only renders, which is most of the world's prose",
        old='    return "".join(ch for ch in value if ch.isprintable())',
        new='    return "".join(ch for ch in value if ch.isascii() and ch.isprintable())',
        caught_by="test_store_claims.py",
    ),
    # #46, moved here with the guard. Three shapes, three mutations, because one guard covering all
    # of them would pass on any single half and the messages are deliberately different: a leading
    # `/` is a habit, a `..` is a misunderstanding, an invisible character is a paste.
    Mutation(
        module="store",
        rule="a scope path cannot be absolute, because the field is relative",
        old='    if value.startswith("/"):',
        new="    if False:",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="and cannot climb out with ..",
        old='    if ".." in value.split("/"):',
        new="    if False:",
        caught_by="test_store_claims.py",
    ),
    # The over-refusing direction, which is the one a guard like this actually fails in. `..` is a
    # whole component or it is nothing: as a substring it takes `a..b` and `..bashrc`, both ordinary
    # names, and the failure is a handoff or a claim that simply never posts - so nobody reports it
    # as a bug, they just stop using the flag. Worth its own entry because every check above is
    # satisfied by a guard that refuses too much.
    Mutation(
        module="store",
        rule="and .. means a whole component, so an ordinary name containing dots still passes",
        old='    if ".." in value.split("/"):',
        new='    if ".." in value:',
        caught_by="test_store_claims.py",
    ),
    # The third shape, and the one the other two made necessary. `\t/etc` starts with a tab, so the
    # check above passes it, and every renderer strips the tab and shows `/etc` - the refused shape,
    # manufactured after the refusal ran. A refusal rather than a strip, so that a stored scope is
    # the same string the reader sees and the same string the matcher compares.
    Mutation(
        module="store",
        rule="a scope cannot hold a character that renders as nothing",
        old="    if shown != value:",
        new="    if False:",
        caught_by="test_store_claims.py",
    ),
    # And the message that refusal comes back with, which is a separate rule because the refusal
    # itself passes without it. Carrying only the stripped form refused `\t/etc` with "it reads as
    # /etc", and `/etc` is a string the typist can see nothing wrong with, so the refusal read as
    # arbitrary and there was nothing in it to act on. For a value that is invisible end to end the
    # stripped form is empty and the message said nothing whatsoever.
    Mutation(
        module="store",
        rule="and the refusal names the codepoints, a stripped form alone not being actionable",
        old='            f"{flag} cannot hold characters a terminal does not show: {dropped}. "',
        new='            f"{flag} cannot hold characters a terminal does not show. "',
        caught_by="test_store_claims.py",
    ),
    # `dict.fromkeys` and not the value itself, which is the shape a later reader removes as noise.
    # A paste with forty non-breaking spaces in it lists U+00A0 forty times otherwise, and the list
    # is there to be read.
    Mutation(
        module="store",
        rule="and names each one once however many times it occurs",
        old='            f"U+{ord(ch):04X}" for ch in dict.fromkeys(value) if printable(ch) != ch',
        new='            f"U+{ord(ch):04X}" for ch in value if printable(ch) != ch',
        caught_by="test_store_claims.py",
    ),
    # #53. A `.tmp-` file is inert because `read_each` filters the name, and that is also why
    # nothing has ever mentioned one. Inert and invisible at once is one property too many: the
    # filter is load-bearing for correctness now - a counted temp file would be a move at a
    # position nobody wrote - so the day it goes is the day the litter starts being read.
    Mutation(
        module="store",
        rule="a half-written file left behind by a killed writer is reported",
        old="        for path in found:",
        new="        for path in []:",
        caught_by="test_cli.py",
    ),
    # Both writers, not the one the issue happened to be about. `claims` goes through `_staged` too.
    Mutation(
        module="store",
        rule="in every directory this store writes into, not only the handoffs",
        old="    directories = [marker_path(root).parent, sessions_dir(root), handoffs_dir(root)]",
        new="    directories = [marker_path(root).parent, handoffs_dir(root)]",
        caught_by="test_cli.py",
    ),
    # And the directory above both, which is where the marker is staged, so an `init` killed between
    # the write and the link leaves litter too. Missing from the first cut of this sweep, under a
    # docstring that said "every directory this store writes into" - the narrower-than-the-problem
    # shape, in the fix for it.
    Mutation(
        module="store",
        rule="including the one the marker itself is staged into, above the records",
        old="    directories = [marker_path(root).parent, sessions_dir(root), handoffs_dir(root)]",
        new="    directories = [sessions_dir(root), handoffs_dir(root)]",
        caught_by="test_cli.py",
    ),
    # And one directory further down again, which is where a move's temp file lands.
    Mutation(
        module="store",
        rule="including the moves directories under the records",
        old="    directories += [path for path in moves if path.is_dir()]",
        new="    directories += []",
        caught_by="test_cli.py",
    ),
    # #61. The text half of the caps. Both directions, because a capper that never cuts and one that
    # always appends a count are different lies: the first reads as the whole of what the sender
    # wrote, the second says characters were dropped from a line nothing was dropped from.
    Mutation(
        module="store",
        rule="text longer than the cap is cut, so one row cannot take a terminal",
        old="    if len(value) <= cap:",
        new="    if False:",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="and text inside it is returned whole, with nothing appended",
        old="    if len(value) <= cap:",
        new="    if True:",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="what was cut off is counted rather than silently dropped",
        old='    return f"{value[:cap]} +{len(value) - cap} more chars"',
        new="    return value[:cap]",
        caught_by="test_store_claims.py",
    ),
    # The marker is one path in one function, for the reason `TMP_PREFIX` is one constant: `init`
    # writing a file `config` does not read would leave every cap at its default with a marker in
    # the repo saying otherwise, and nothing would fail.
    Mutation(
        module="store",
        rule="the marker is the file init writes and config reads, at one path",
        old='    return pathlib.Path(root) / ".claude" / "exchange.json"',
        new='    return pathlib.Path(root) / "exchange.json"',
        caught_by="test_cli.py",
    ),
    Mutation(
        module="store",
        rule="a list past its cap says how many it left out",
        old="    if extra <= 0:\n        return shown\n    return f",
        new="    if True:\n        return shown\n    return f",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="store",
        rule="a filename in a read problem is stripped, since this plugin may not have written it",
        old="    name = printable(path.name)",
        new="    name = path.name",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="and the name each schema problem is prefixed with",
        old="        problems = validate.validate(obj, schema, name)",
        new="        problems = validate.validate(obj, schema, path.name)",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="a half-written file is named stripped",
        old="{printable(directory.name)}/{printable(path.name)} is a half-written file left ",
        new="{printable(directory.name)}/{path.name} is a half-written file left ",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="and so is the directory it was found in, which for a moves directory came off disk",
        old="{printable(directory.name)}/{printable(path.name)} is a half-written",
        new="{directory.name}/{printable(path.name)} is a half-written",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="a failed cleanup is swallowed, not raised past the problem already being reported",
        old="    except OSError:\n        pass",
        new="    except OSError:\n        raise",
        caught_by="test_store_claims.py",
    ),
]

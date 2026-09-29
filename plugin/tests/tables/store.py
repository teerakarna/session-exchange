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
            '        return None, f"{path.name} could not be read: {exc}"'
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
        rule="a scope path cannot be absolute, because the field is relative to the root",
        old='    if value.startswith("/"):',
        new="    if False:",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="and cannot climb out of the root with ..",
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
]

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
]

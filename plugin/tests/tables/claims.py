"""The rules `claims.py` has to keep, one broken way each."""

from .shape import Mutation

# Claims are the only genuinely new state this plugin keeps, and the only state another session
# reads. The registry can say a session is alive; nothing but a claim can say what it is doing, and
# a wrong claim is worse than none - it is a peer confidently reported as working somewhere it is
# not, which is the failure the whole exchange exists to remove.
MUTATIONS = [
    Mutation(
        module="claims",
        rule="claims live in the store, not loose in the root",
        old='    return store.sessions_dir(root) / f"{session_id}.json"',
        new='    return pathlib.Path(root) / f"{session_id}.json"',
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="the branch is found from a subdirectory, not only from the repo root",
        old="    for candidate in (pathlib.Path(cwd), *pathlib.Path(cwd).parents):",
        new="    for candidate in (pathlib.Path(cwd),):",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="the ref prefix is stripped, so the field holds a branch and not a ref",
        old=(
            '        return text[len("ref: refs/heads/") :] '
            'if text.startswith("ref: refs/heads/") else None'
        ),
        new='        return text if text.startswith("ref: refs/heads/") else None',
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="a detached head is no branch, not a sha wearing the name of one",
        old=(
            '        return text[len("ref: refs/heads/") :] '
            'if text.startswith("ref: refs/heads/") else None'
        ),
        new=(
            '        return text[len("ref: refs/heads/") :] '
            'if text.startswith("ref: refs/heads/") else text'
        ),
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="a HEAD that cannot be read is no branch, and not an exception either",
        old="        except (OSError, UnicodeDecodeError):\n            return None",
        new="        except (OSError, UnicodeDecodeError):\n            raise",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="a HEAD that is not text is one of the ways it cannot be read",
        old="        except (OSError, UnicodeDecodeError):",
        new="        except OSError:",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="re-seeding keeps what the session said about itself",
        old="    claim = dict(existing) if existing else {}",
        new="    claim = {}",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="a seeded claim carries the session it is about",
        old="    claim.update(session_id=session_id, cwd=str(cwd), updated_at=store.now())",
        new="    claim.update(cwd=str(cwd), updated_at=store.now())",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="a branch that has gone away is removed rather than left behind",
        old='    elif "git_branch" in claim:\n        del claim["git_branch"]',
        new='    elif "git_branch" in claim:\n        pass',
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="a seed that could not be written returns the problem, not the claim",
        old=(
            "    write_problem = store.write_json(path(root, session_id), claim, SCHEMA)\n"
            "    return (None, write_problem) if write_problem else (claim, problem)"
        ),
        new=(
            "    write_problem = store.write_json(path(root, session_id), claim, SCHEMA)\n"
            "    return claim, problem"
        ),
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="an unusable session id is refused by update too, not only by seed",
        old=(
            "    session_id = store.safe_id(session_id)\n"
            "    if session_id is None:\n"
            '        return None, "session id is not usable as a filename"'
        ),
        new=(
            "    session_id = store.safe_id(session_id)\n"
            "    if session_id is None:\n"
            "        return None, None"
        ),
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="updating a claim that is not there explains itself rather than half-succeeding",
        old=(
            "        return None, problem or "
            '"no claim for this session yet; it is seeded at session start"'
        ),
        new="        return claim, None",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="an empty focus is a focus being cleared, not an argument that was not passed",
        old="    if focus is not None:",
        new="    if focus:",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="replacing a list deduplicates it, the same as adding does",
        old="        claim[field] = list(dict.fromkeys(values))",
        new="        claim[field] = list(values)",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="adding keeps what was already there",
        old="        claim[field] = list(dict.fromkeys(list(claim.get(field, [])) + list(values)))",
        new="        claim[field] = list(dict.fromkeys(list(values)))",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="adding deduplicates rather than repeating a repo the session already named",
        old="        claim[field] = list(dict.fromkeys(list(claim.get(field, [])) + list(values)))",
        new="        claim[field] = list(claim.get(field, [])) + list(values)",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="clearing a field removes it rather than emptying it",
        old="        claim.pop(field, None)",
        new="        claim[field] = []",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="an update touches the timestamp, or a session that just spoke reads as stale",
        old='    claim["updated_at"] = store.now()',
        new="    pass",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="clearing a claim that is already gone is success, because session end fires twice",
        old="        path(root, session_id).unlink(missing_ok=True)",
        new="        path(root, session_id).unlink()",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="a claim that could not be cleared says so, rather than looking like a live peer",
        old='        return f"could not clear claim: {exc}"',
        new="        return None",
        caught_by="test_store_claims.py",
    ),
    # #47's claim half. One per field again, for the reason the handoff half records: a single check
    # over three fields passes as soon as one of them is stripped, and the other two then have no
    # check at all. `show` renders five claim fields and none of them carries a pattern.
    Mutation(
        module="claims",
        rule="a focus another session wrote goes through the stripper",
        old=(
            "    return store.capped_text("
            'store.printable(claim.get("focus") or "(no focus stated)"), cap)'
        ),
        new=('    return store.capped_text((claim.get("focus") or "(no focus stated)"), cap)'),
        caught_by="test_store_claims.py",
    ),
    # Stripping after capping is the subtle half, and it is a separate entry because a check that
    # only asserts the escape is gone passes either way. What it costs is a row shorter than the cap
    # by however many invisible characters the writer put in front of the text.
    Mutation(
        module="claims",
        rule="and is stripped before it is capped, so the cap counts what the reader sees",
        old=(
            "    return store.capped_text("
            'store.printable(claim.get("focus") or "(no focus stated)"), cap)'
        ),
        new=(
            "    return store.printable("
            'store.capped_text(claim.get("focus") or "(no focus stated)", cap))'
        ),
        caught_by="test_store_claims.py",
    ),
    # And that it is capped at all. The two above both cap, so either of them passing says nothing
    # about the bound existing - which is how the one render with no bound at all went unnoticed
    # until #61 was filed about a different field.
    Mutation(
        module="claims",
        rule="and it is capped, a focus being free text with no length limit in the schema",
        old=(
            "    return store.capped_text("
            'store.printable(claim.get("focus") or "(no focus stated)"), cap)'
        ),
        new='    return store.printable(claim.get("focus") or "(no focus stated)")',
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="so does a display name, which is copied out of another session's registry entry",
        old='    return store.printable(claim.get("name") or claim["session_id"])',
        new='    return claim.get("name") or claim["session_id"]',
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="claims",
        rule="and every element of a list field, not the first one",
        old="    return [store.printable(v) for v in values]",
        new="    return [store.printable(values[0])] + list(values[1:])",
        caught_by="test_store_claims.py",
    ),
    # The echo, which is the second render of a claim and the one the four above missed. `exchange
    # claim --session` reads back a record belonging to another session, so these are the same three
    # fields one command over. Caught in `test_cli.py` because the echo only exists as a command's
    # output: there is no other caller to assert against.
    Mutation(
        module="claims",
        rule="the echo confirming a claim strips the focus it reads back",
        old="        lines.append(f\"  focus: {store.printable(claim['focus'])}\")",
        new="        lines.append(f\"  focus: {claim['focus']}\")",
        caught_by="test_cli.py",
    ),
    Mutation(
        module="claims",
        rule="and the name it leads with",
        old='    lines = [f"claimed as {describe_name(claim)}"]',
        new="    lines = [f\"claimed as {claim.get('name') or claim['session_id']}\"]",
        caught_by="test_cli.py",
    ),
    Mutation(
        module="claims",
        rule="and every list field in it",
        old="            lines.append(f\"  {field}: {', '.join(describe_list(claim[field]))}\")",
        new="            lines.append(f\"  {field}: {', '.join(claim[field])}\")",
        caught_by="test_cli.py",
    ),
    Mutation(
        module="claims",
        rule="a claim's scope is every list field it holds",
        old="        for field in LIST_FIELDS\n        if claim.get(field)\n    ]",
        new="        for field in LIST_FIELDS[:1]\n        if claim.get(field)\n    ]",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="claims",
        rule="each element of a claim's scope is stripped",
        old="        (field, store.capped_list(describe_list(claim[field]), cap))",
        new="        (field, store.capped_list(list(claim[field]), cap))",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="claims",
        rule="a claim's scope is capped",
        old="        (field, store.capped_list(describe_list(claim[field]), cap))",
        new="        (field, store.capped_list(describe_list(claim[field]), 10**9))",
        caught_by="test_hook.py",
    ),
]

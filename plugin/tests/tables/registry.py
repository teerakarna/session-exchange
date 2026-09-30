"""The rules `registry.py` has to keep, one broken way each."""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="registry",
        rule="liveness is checked rather than assumed",
        old="        os.kill(int(pid), 0)",
        new="        int(pid)",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a pid that arrives as a string is coerced, not read as dead",
        old="        os.kill(int(pid), 0)",
        new="        os.kill(pid, 0)",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="something that is not a pid at all is not alive, and not an exception either",
        old="    except (OSError, TypeError, ValueError):",
        new="    except OSError:",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a pid that cannot be signalled reads as dead, not as alive",
        old="    except (OSError, TypeError, ValueError):\n        return False",
        new="    except (OSError, TypeError, ValueError):\n        return True",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a pid that can be signalled reads as alive",
        old="    return True",
        new="    return False",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # The only argument this module takes that is not a pid, and the first thing done to it is
        # `.is_dir()`. Every caller inside the plugin passes a Path, so the coercion is for the ones
        # outside it, which is exactly the set no existing check stood in for.
        rule="a directory given as a string is still a directory",
        old="    sessions_dir = pathlib.Path(sessions_dir)",
        new="    sessions_dir = sessions_dir",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a file that will not parse is skipped, not raised",
        old="        except (OSError, ValueError):\n            continue",
        new="        except OSError:\n            continue",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="one bad file costs one row, not the rest of the directory",
        old="        except (OSError, ValueError):\n            continue",
        new="        except (OSError, ValueError):\n            break",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a row has to be an object, because a list has no .get",
        old='        if not isinstance(row, dict) or not row.get("sessionId"):',
        new='        if not row.get("sessionId"):',
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a row with no session id is not a session",
        old='        if not isinstance(row, dict) or not row.get("sessionId"):',
        new="        if not isinstance(row, dict):",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a dead session's row is left out by default",
        old='        if live_only and not alive(row.get("pid")):',
        new="        if live_only and False:",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="and included when the caller says liveness is not the question",
        old='        if live_only and not alive(row.get("pid")):',
        new='        if not alive(row.get("pid")):',
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # The module's own docstring calls this out, and nothing asserted it. A recycled pid is the
        # whole reason: the stem was written by whatever process held that number at the time.
        rule="the pid is read from inside the file, not from its name",
        old='        if live_only and not alive(row.get("pid")):',
        new="        if live_only and not alive(path.stem):",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="rows come back sorted, because presence is rendered straight from them",
        old='    return sorted(rows, key=lambda r: str(r.get("name") or r.get("sessionId")))',
        new="    return rows",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a row with no name sorts by its id, not by the string None",
        old='    return sorted(rows, key=lambda r: str(r.get("name") or r.get("sessionId")))',
        new='    return sorted(rows, key=lambda r: str(r.get("name")))',
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # A SessionEnd hook is the caller that needs this: by the time it runs, the session it is
        # naming may already be gone, and filtering on liveness would lose exactly that row.
        rule="a session that has just died still resolves by id",
        old="        rows = entries(sessions_dir, live_only=False, peers_only=False)",
        new="        rows = entries(sessions_dir, peers_only=False)",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="an id matches exactly, not as a prefix",
        old='        if row.get("sessionId") == session_id:',
        new='        if str(row.get("sessionId")).startswith(session_id):',
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="the row returned is the one whose id matched",
        old='        if row.get("sessionId") == session_id:',
        new='        if row.get("sessionId") != session_id:',
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="the walk is bounded, so a cycle cannot hang a command",
        old="    for _ in range(limit):",
        new="    for _ in range(limit + 1):",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="pid 1 is where the walk stops, not another step",
        old="        if current <= 1:",
        new="        if current < 1:",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # Nearest first is not cosmetic: `own_entry` takes the first match, so the order of this
        # list is what decides which session a nested command belongs to.
        rule="the chain runs nearest first",
        old="        chain.append(current)",
        new="        chain.insert(0, current)",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a ps that is not there ends the walk rather than raising",
        old="        except (OSError, subprocess.SubprocessError):",
        new="        except subprocess.SubprocessError:",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a ps that hangs past the timeout ends the walk too",
        old="        except (OSError, subprocess.SubprocessError):",
        new="        except OSError:",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="ps output is stripped, or every parent reads as unusable",
        old="        parent = out.stdout.strip()",
        new="        parent = out.stdout",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="output that is not a number ends the walk instead of being parsed",
        old="        if not parent.isdigit():\n            break",
        new="        if not parent.isdigit():\n            pass",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="a row whose pid is not a number is skipped, not parsed anyway",
        old='        if str(r.get("pid", "")).isdigit()',
        new="        if True",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # The case every command run through a tool call is in: several processes below the session,
        # so its own pid is in no registry file and only an ancestor's is.
        rule="the process tree is walked, not just this process",
        old="    for pid in _parents(os.getpid()):",
        new="    for pid in [os.getpid()]:",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="the nearest matching session wins, not the outermost",
        old="    for pid in _parents(os.getpid()):",
        new="    for pid in reversed(_parents(os.getpid())):",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # The defect shape worth naming: not "no session", which every command handles, but
        # "somebody else's session", which they all act on.
        rule="no match is no session, rather than whichever row was first",
        old="            return rows[pid]\n    return None",
        new="            return rows[pid]\n    return next(iter(rows.values()), None)",
        caught_by="test_registry.py",
    ),
    # #31. A row that is not a peer, and the four lines that decide which callers see one.
    Mutation(
        module="registry",
        rule="a background job is not rendered as somebody to coordinate with",
        old="        if peers_only and not is_peer(row):\n            continue",
        new="        if False:\n            continue",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="and a caller that says peerhood is not the question still gets it",
        old="        if peers_only and not is_peer(row):",
        new="        if not is_peer(row):",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # The direction of the predicate, which is the whole of #31's judgement call: a blocklist
        # renders one row too many when Claude Code invents a kind, an allowlist renders nobody.
        rule="a row with no kind, or a kind nothing here knows, is a peer",
        old='    return row.get("kind") not in NOT_PEERS',
        new='    return row.get("kind") == "interactive"',
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # An identity lookup that filtered would answer None for a background job, which is the
        # same answer it gives for an id the registry never had - and the hook branches on the
        # difference.
        rule="resolving an id by name sees every kind of row",
        old="        rows = entries(sessions_dir, live_only=False, peers_only=False)",
        new="        rows = entries(sessions_dir, live_only=False)",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # Inside a background job the chain holds two registry pids, and nearest-first picks the
        # job. Everything downstream then writes under an id no presence render shows.
        rule="own_entry skips a background row for the session that spawned it",
        old="def own_entry(sessions_dir=SESSIONS_DIR, peers_only=True):",
        new="def own_entry(sessions_dir=SESSIONS_DIR, peers_only=False):",
        caught_by="test_registry.py",
    ),
    # The three a review of this table found, each a line no mutation here offered and no check
    # read, all three verified green before the checks went in. Two of them are rules
    # `test_registry.py` already asserts correctly one function over, which is the shape worth
    # naming: a file can carry a rule and drop it a few lines later, and a table written from the
    # same reading drops it twice.
    Mutation(
        module="registry",
        # The seam that made the `except` assertable did not make the timeout assertable, because a
        # stand-in that raises unconditionally reaches the same arm whether the call is bounded or
        # not. A hung `ps` is the failure the bound exists for and it hangs a session start.
        rule="the ps call is bounded, not merely guarded",
        old="                timeout=5,\n",
        new="",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # Asserted for `alive` one function up and silently dropped here, where it decides whether a
        # command can learn its own session id at all. Every fixture in the file wrote an int, so an
        # int-keyed dict and a raw-keyed one agreed on all of them.
        rule="a pid that arrives as a string keys the same row as an int",
        old='        int(r["pid"]): r',
        new='        r["pid"]: r',
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        # Written up as unfalsifiable on the grounds that the answer is None either way. True of the
        # answer, false of the behaviour: what it skips is a directory read, which is observable.
        rule="an empty id is answered without reading the directory",
        old="    if not session_id:\n        return None",
        new="    if False:\n        return None",
        caught_by="test_registry.py",
    ),
    Mutation(
        module="registry",
        rule="own_entry can be asked for the nearest row whatever its kind",
        old="entries(sessions_dir, live_only=False, peers_only=peers_only)",
        new="entries(sessions_dir, live_only=False)",
        caught_by="test_registry.py",
    ),
]

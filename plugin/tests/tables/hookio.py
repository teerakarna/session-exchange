"""The rules `hookio.py` has to keep, one broken way each."""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="hookio",
        rule="the event name is read from the payload, not from the wiring",
        old="    return name if isinstance(name, str) and name else default",
        new="    return default",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a payload with no event name falls back to the wiring",
        old="    return name if isinstance(name, str) and name else default",
        new="    return name",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a payload event name that is not a string falls back too",
        old="    return name if isinstance(name, str) and name else default",
        new="    return name if name else default",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="nothing to say means nothing printed, not an empty section",
        old="    lines = [line for line in lines if line]\n    if not lines:\n        return",
        new="    lines = [line for line in lines if line]\n    if False:\n        return",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a handler run by hand on a terminal returns instead of waiting forever",
        old="        if stream.isatty():\n            return {}",
        new="        if False:\n            return {}",
        caught_by="test_hook.py",
    ),
    # The three the first honest sweep found alive, in a module already recorded as swept. Each one
    # is a rule the module's docstring or a function's docstring states, with nothing behind it.
    Mutation(
        module="hookio",
        rule="a problem line is marked as coming from this plugin",
        old='    return f"[{PREFIX}] {text}"',
        new="    return text",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="lines are joined by a newline, not run together",
        old='"\\n".join(lines)',
        new='" ".join(lines)',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="an empty line is dropped rather than injected as a gap",
        old="    lines = [line for line in lines if line]",
        new="    lines = list(lines)",
        caught_by="test_hook.py",
    ),
    # And the rest, found by review passes over this diff rather than by the first sweep, all in the
    # same module again. The first is the worst of every survivor: it breaks the guarantee the
    # project calls absolute.
    Mutation(
        module="hookio",
        rule="valid JSON that is not an object is no payload, not an exit 1 with a traceback",
        old="    return data if isinstance(data, dict) else {}",
        new="    return data",
        caught_by="test_hook.py",
    ),
    # And the half-fix this entry was first written against, worth its own mutation: `or {}` turns
    # the falsy non-objects into `{}` and passes `5`, `true` and `[1]` straight through, so a suite
    # that only ever feeds it `null` reads as cover for a guarantee still broken four ways.
    Mutation(
        module="hookio",
        rule="a truthy non-object is caught too, not just the falsy half",
        old="    return data if isinstance(data, dict) else {}",
        new="    return data or {}",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="the stream argument is the stream that gets read",
        old="    stream = sys.stdin if stream is None else stream",
        new="    stream = sys.stdin",
        caught_by="test_hook.py",
    ),
    # Named for what it breaks, which is the opposite of what its text said for two passes: this one
    # makes `emit` return unconditionally and inject nothing ever, while the entry above is the one
    # about an empty section. Two entries claiming the same rule reads as a duplicate and gets
    # deleted, taking the rule nothing else covers with it.
    Mutation(
        module="hookio",
        rule="having something to say means a reply is printed at all",
        old="    if not lines:\n        return",
        new="    return",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a stream that cannot answer isatty is read rather than refused",
        old="    except (AttributeError, ValueError):\n        pass",
        new="    except ZeroDivisionError:\n        pass",
        caught_by="test_hook.py",
    ),
    # And the read below that guard, which named its exception types and was wrong about them three
    # passes running: `sys.stdin` is `None` when fd 0 is not open, a non-blocking stdin reads as
    # `None`, and a deeply nested array raises `RecursionError`. The mutation is the list coming
    # back, because the list is the defect rather than any one type missing from it.
    Mutation(
        module="hookio",
        rule="anything at all going wrong on the read is no payload, not a traceback out of main",
        old="    except Exception:\n        return {}",
        new="    except (ValueError, OSError):\n        return {}",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="the reply is shaped the way Claude Code reads it, key included",
        old='            "hookSpecificOutput": {',
        new='            "hookSpecificOutputs": {',
        caught_by="test_hook.py",
    ),
    # The reader half of the guarantee, one mutation per state of it, because the first version of
    # this fix closed one of the three and the docstring claimed all three. A check fed back exactly
    # the input that showed the bug is the `or {}` shape again, one file over.
    #
    # The body removed rather than weakened. The two weaker versions - catching the `OSError` and
    # doing nothing, or flushing inside a wrapped `print` - both still exit 120, so either as a
    # `new` would be caught for a reason that has nothing to do with the rule.
    Mutation(
        module="hookio",
        rule="a stdout nobody is reading is silence, not an exit 120 on the way out",
        old="            null = os.open(os.devnull, os.O_WRONLY)\n"
        "            os.dup2(null, 1)\n"
        "            os.close(null)",
        new="            pass",
        caught_by="test_hook.py",
    ),
    # The write inside the same `try` as the flush. Expressed as the whole block swapped for the
    # version this was, with the `print` outside, because that is the shape of the defect: buffered,
    # the write succeeds and the flush is where the pipe breaks, so a fix that only guards the flush
    # passes every check written for the buffered case and raises on the unbuffered one.
    Mutation(
        module="hookio",
        rule="an unbuffered stdout breaks during the write, which is inside the guard too",
        old=(
            "    try:\n"
            "        print(reply, file=stream)\n"
            "        stream.flush()\n"
            "    except OSError:"
        ),
        new=(
            "    print(reply, file=stream)\n    try:\n        stream.flush()\n    except OSError:"
        ),
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="no stdout at all is silence, not an AttributeError out of a hook",
        old="    if stream is None:\n        return",
        new="    if False:\n        return",
        caught_by="test_hook.py",
    ),
    # The narrowing guard on the redirect, which had thirteen lines of comment defending it and
    # nothing behind it: `if True` left the whole suite green, so the rule that `out=` is a seam and
    # not an fd was protection that was not.
    Mutation(
        module="hookio",
        rule="a stream the caller handed in is never fixed by redirecting fd 1",
        old="        if stream is sys.__stdout__:",
        new="        if True:",
        caught_by="test_hook.py",
    ),
]

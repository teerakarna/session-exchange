#!/usr/bin/env python3
"""The store and the claims on top of it.

Two properties carry most of the weight, and both are asserted by breaking them:

- An invalid object never reaches disk. Validating after writing would leave a reader having to tell
  a corrupt file from one written by a newer version, which is a distinction nobody can make.
- A file that exists and cannot be read is never reported as "nothing here". Collapsing those two is
  how a dead parser read as a quiet day for ten days.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import claims
import store
import validate

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


CLAIM_SCHEMA = validate.load("claim")

print("write, read, and the difference between missing and unreadable")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    good = {"session_id": "s1", "cwd": str(root), "updated_at": store.now()}
    path = claims.path(root, "s1")

    check("a valid claim writes", store.write_json(path, good, CLAIM_SCHEMA), None)
    check("and reads back", store.read_json(path, CLAIM_SCHEMA), (good, None))
    check("a missing file is nothing here, not a problem",
          store.read_json(claims.path(root, "absent"), CLAIM_SCHEMA), (None, None))

    path.write_text("{ truncated")
    obj, problem = store.read_json(path, CLAIM_SCHEMA)
    check("a file that exists and will not parse says so",
          (obj, problem is not None), (None, True))

    path.write_text(json.dumps({"session_id": "s1"}))
    obj, problem = store.read_json(path, CLAIM_SCHEMA)
    check("a file that parses and is invalid also says so",
          (obj, "updated_at" in (problem or "")), (None, True))

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    path = claims.path(root, "s1")
    problem = store.write_json(path, {"session_id": "s1"}, CLAIM_SCHEMA)
    # Break it: if validation happened after the write, or not at all, the file would be here.
    check("an invalid claim never reaches disk",
          (problem is not None, path.exists()), (True, False))
    check("and no stray temp file is left behind",
          sorted(p.name for p in path.parent.glob("*")) if path.parent.is_dir() else [], [])

print("an identifier that is also a filename")

check("a plain id passes", store.safe_id("abc-123.def"), "abc-123.def")
for bad in ("../escape", "a/b", "", None, "with space"):
    check(f"{bad!r} is refused rather than rewritten", store.safe_id(bad), None)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    claim, problem = claims.seed(root, "../../evil", root)
    check("seeding with a traversing id writes nothing",
          (claim, problem is not None), (None, True))
    check("and nothing appeared outside the store",
          list(root.parent.glob("evil*")), [])

print("seed, update, clear")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/feat/thing\n")

    claim, problem = claims.seed(root, "s1", root, name="pane-a")
    check("a seeded claim carries what the payload knows",
          (claim["session_id"], claim["name"], claim.get("git_branch"), problem),
          ("s1", "pane-a", "feat/thing", None))

    (root / ".git" / "HEAD").write_text("9d4f1c0e" * 5 + "\n")
    claim, _ = claims.seed(root, "s1", root)
    check("a detached head is no branch rather than a sha-shaped one",
          "git_branch" in claim, False)

    claims.update(root, "s1", focus="the thing", add={"paths": ["a", "b"]})
    claim, _ = claims.update(root, "s1", add={"paths": ["b", "c"], "repos": ["dotfiles"]})
    check("adding to a list deduplicates rather than repeating",
          (claim["paths"], claim["repos"]), (["a", "b", "c"], ["dotfiles"]))

    # SessionStart fires again on resume and on compact. Wiping the focus then would be a
    # regression the session itself cannot see.
    claim, _ = claims.seed(root, "s1", root)
    check("re-seeding keeps what the session said about itself",
          (claim["focus"], claim["paths"]), ("the thing", ["a", "b", "c"]))

    claim, _ = claims.update(root, "s1", replace={"paths": ["only"]})
    check("replacing a list replaces it", claim["paths"], ["only"])
    claim, _ = claims.update(root, "s1", clear_fields=["paths"])
    check("clearing removes the field entirely", "paths" in claim, False)

    held, problems = claims.load_all(root)
    check("one claim under this root", (len(held), problems), (1, []))

    check("clearing a claim succeeds", claims.clear(root, "s1"), None)
    check("and the file is gone", claims.path(root, "s1").exists(), False)
    # SessionEnd can fire for a session that never claimed, and can fire twice.
    check("clearing again is still success", claims.clear(root, "s1"), None)

    claim, problem = claims.update(root, "s1", focus="x")
    check("updating a claim that does not exist explains itself",
          (claim, problem is not None), (None, True))

print("one unreadable file does not hide the readable ones, or the reverse")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    claims.seed(root, "s1", root)
    claims.seed(root, "s2", root)
    (store.sessions_dir(root) / "s3.json").write_text("{ nope")
    held, problems = claims.load_all(root)
    check("two read, one reported", (len(held), len(problems)), (2, 1))

print("the marker's defaults come from the schema, not from a second copy of them")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    (root / ".claude").mkdir()
    (root / ".claude" / "exchange.json").write_text(json.dumps({"name": "personal"}))
    config, problem = store.config(root)
    check("a marker with only a name still yields every cap",
          (config["name"], config["stale_days"], config["max_handoffs_listed"], problem),
          ("personal", 7, 8, None))

    (root / ".claude" / "exchange.json").write_text(json.dumps({"name": "x", "stale_days": "7"}))
    config, problem = store.config(root)
    # Refusing to render because one cap is misspelt would be the wrong trade. Doing it silently
    # would be worse than either.
    check("an invalid marker yields defaults and a problem, not one or the other",
          (config["stale_days"], problem is not None), (7, True))

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

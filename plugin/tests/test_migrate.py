#!/usr/bin/env python3
"""Migration step 4, against a real store in a temporary root and a ledger written next to it.

The claims worth breaking are the ones an importer gets wrong quietly. A second run that posts again
is a duplicate nobody asked for. A run that writes half and stops is a store that cannot say which
half was meant. A recipient with no route posted somewhere anyway is a handoff nobody reads, which
is the failure this project exists to end. And a body edit in the ledger written back would break
the one rule the store is built on, that a record is written once. Each is asserted from both sides:
the refusal, and the case next to it that has to go through.
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import handoffs
import ledger
import migrate
import store

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
CENSUS = (FIXTURES / "handoffs.md").read_text()
A = ledger.ARROW

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def rooted(tmp, text):
    root = pathlib.Path(tmp).resolve()
    store.handoffs_dir(root).mkdir(parents=True)
    (root / "ledger.md").write_text(text)
    return root


def held(root):
    found, problems = handoffs.load_all(root)
    assert not problems, problems
    return found


CENSUS_ROUTES = {
    "Lane B": {"repo": "b"},
    "lane e / f": {"repo": "ef"},
    "Lane B + Lane C / D + Lane G": {"repo": "b", "paths": ["shared"]},
}

SMALL = (
    "## Open questions / handoffs\n\n"
    f"**[Lane A {A} Lane B]** 2026-01-02 - first thing\n\nbody one\n\n"
    f"**[Lane A {A} Lane B]** 2026-01-03 - second thing\n\nbody two\n"
)
SMALL_BLOCK = {"path": "ledger.md", "routes": {"Lane B": {"repo": "b"}}}


print("the census: five open, five closed, three routes")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp, CENSUS)
    block = {"path": "ledger.md", "routes": CENSUS_ROUTES}
    first = migrate.prepare(root, block)
    check("no problem", first.problems, [])
    check("every entry parsed", first.parsed, 10)
    check("the five open ones are to be created", len(first.plan.create), 5)
    check("and the five closed ones skipped, never created", len(first.plan.skipped), 5)
    check("a plan writes nothing", held(root), [])
    lines, problems = migrate.apply(root, first)
    check("applying posts all five", (len(lines), problems), (5, []))
    stored = held(root)
    check("five records, all open", sorted(status for _, status in stored), ["open"] * 5)
    wide = [r for r, _ in stored if r["to"].get("paths")]
    check(
        "a recipient group mapped as a whole goes to that group's scope",
        [r["to"] for r in wide],
        [{"repo": "b", "paths": ["shared"]}],
    )
    # Picked by body rather than by date, so a broken date fails the date check below instead of
    # failing to find the record at all.
    sample = next((r for r, _ in stored if "canonical shape" in r["body"]), {"from": {}})
    # Staleness reads `created`, so the import's own clock would make a nine-day-old entry fresh.
    check(
        "created is the ledger's date, not the import's",
        sample.get("created"),
        "2026-01-02T00:00:00Z",
    )
    check("the sender is the ledger's sender", sample["from"].get("name"), "Lane A")
    check("and the cwd is the root", sample["from"].get("cwd"), str(root))
    check(
        "the importer's key is on the record",
        sorted(sample.get("imported", {})),
        ["date", "headline", "route"],
    )

    again = migrate.prepare(root, block)
    check(
        "a second run has nothing to do",
        (len(again.plan.create), len(again.closes), len(again.plan.unchanged), again.problems),
        (0, 0, 5, []),
    )
    check("and says so as zero outstanding", migrate.outstanding(again), 0)
    lines, problems = migrate.apply(root, again)
    check("and applying it writes nothing", (lines, problems, len(held(root))), ([], [], 5))

print()
print("refusing, and writing nothing when it does")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp, CENSUS)
    routes = {k: v for k, v in CENSUS_ROUTES.items() if k != "lane e / f"}
    plan = migrate.prepare(root, {"path": "ledger.md", "routes": routes})
    check(
        "an unmapped recipient is a problem that names it",
        [p for p in plan.problems if p.startswith("no route for Lane E/F")] != [],
        True,
    )
    check("the mapped entries are still planned, so the report is whole", len(plan.plan.create), 5)
    lines, problems = migrate.apply(root, plan)
    # The four routed entries were fine on their own. Posting them would leave a store that cannot
    # say which of its rows were meant to be the whole import.
    check("and applying writes none of it, not even the routed four", (lines, held(root)), ([], []))
    check("and says why", problems, ["the plan has problems, so nothing was written"])

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp, CENSUS)
    routes = {
        "Lane B": {"repo": "b"},
        "Lane E/F": {"repo": "ef"},
        "Lane C/D": {"repo": "cd"},
        "Lane G": {"repo": "g"},
    }
    plan = migrate.prepare(root, {"path": "ledger.md", "routes": routes})
    check(
        "recipients on separate scopes are a problem, since a handoff has one",
        sum("map to different scopes" in p for p in plan.problems),
        1,
    )
    # Two distinct scopes among three labels, not three, so a count that tolerated one extra would
    # not pass for a refusal.
    routes = dict(routes, **{"Lane C/D": {"repo": "b"}})
    plan = migrate.prepare(root, {"path": "ledger.md", "routes": routes})
    check("two scopes among three labels is still more than one", len(plan.problems), 1)
    routes = dict(routes, **{"Lane G": {"repo": "b"}})
    plan = migrate.prepare(root, {"path": "ledger.md", "routes": routes})
    check("and labels mapped one by one to the same scope go through", plan.problems, [])

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp, SMALL)
    plan = migrate.prepare(root, {"path": "ledger.md", "routes": {"lane b": {"repo": "../b"}}})
    check(
        "a route the store would refuse is refused here, before anything is posted",
        len(plan.problems),
        2,
    )
    plan = migrate.prepare(root, {"path": "ledger.md", "routes": {"LANE  B": {"repo": "b"}}})
    check("route keys compare normalised, like the labels they match", plan.problems, [])
    plan = migrate.prepare(root, {"path": "missing.md"})
    check(
        "an unreadable ledger is a problem, not an empty import",
        plan.problems,
        [f"cannot read {root / 'missing.md'}: FileNotFoundError"],
    )
    plan = migrate.prepare(root, dict(SMALL_BLOCK, section="Elsewhere"))
    check(
        "the section named in the marker is the one read",
        plan.problems,
        ["no heading starts with 'Elsewhere'"],
    )
    plan = migrate.prepare(root, {"path": str(root / "ledger.md"), "routes": SMALL_BLOCK["routes"]})
    check("an absolute path is read as it is", (plan.parsed, plan.problems), (2, []))

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp, SMALL + f"\n**[Lane A {A} Lane B]** 2026-01-02 - first thing\n\nagain\n")
    plan = migrate.prepare(root, SMALL_BLOCK)
    check("two entries reconcile cannot tell apart are a problem", len(plan.problems), 1)
    root = rooted(tmp + "/b", SMALL)
    (store.handoffs_dir(root) / "broken.json").write_text("{")
    plan = migrate.prepare(root, SMALL_BLOCK)
    # An unreadable record may be one this import already wrote, so planning past it could post a
    # second copy of it.
    check("an unreadable record in the store is a problem too", len(plan.problems), 1)

print()
print("after the import: only a closure is written back")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp, SMALL)
    migrate.apply(root, migrate.prepare(root, SMALL_BLOCK))
    before = {r["id"]: r for r, _ in held(root)}
    (root / "ledger.md").write_text(
        SMALL.replace("- first thing", "- first thing **Status:** DONE").replace(
            "body two", "body two, edited after the import"
        )
    )
    plan = migrate.prepare(root, SMALL_BLOCK)
    check("the closure is planned as a close", len(plan.closes), 1)
    check(
        "and both edited entries are reported as drift",
        sorted(sorted(fields) for _, fields in plan.drift),
        [["body"], ["body"]],
    )
    check("a closure is outstanding work, drift is not", migrate.outstanding(plan), 1)
    lines, problems = migrate.apply(root, plan)
    check("applying writes the one close", (len(lines), problems), (1, []))
    after = held(root)
    check("the store has it closed", sorted(status for _, status in after), ["closed", "open"])
    closed = [r["id"] for r, status in after if status == "closed"]
    moves = handoffs.transitions(root, closed[0])[0] if closed else []
    check("as a normal move, naming this command", [m.get("by") for m in moves], [migrate.BY])
    check(
        "and no record was rewritten, body edits included",
        {r["id"]: r for r, _ in after},
        before,
    )
    plan = migrate.prepare(root, SMALL_BLOCK)
    check("a second run closes nothing", (len(plan.closes), migrate.outstanding(plan)), (0, 0))
    check("and still reports the drift, since it is still there", len(plan.drift), 2)

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp, SMALL)
    migrate.apply(root, migrate.prepare(root, SMALL_BLOCK))
    record = held(root)[0][0]
    handoffs.set_status(root, record["id"], handoffs.ACCEPTED)
    plan = migrate.prepare(root, SMALL_BLOCK)
    # The ledger has no word for accepted, so it says open. The store being ahead of the ledger is
    # the direction the migration goes, and writing open back would undo the acceptance.
    check(
        "a store ahead of the ledger is drift, not a move back",
        ([sorted(f) for _, f in plan.drift], plan.closes),
        ([["status"]], []),
    )
    migrate.apply(root, plan)
    check("and applying leaves it accepted", sorted(s for _, s in held(root)), ["accepted", "open"])

print()
print("dates")

check(
    "a dated entry is created on its date",
    migrate.created_of(ledger.entries(SMALL)[0][0]),
    "2026-01-02T00:00:00Z",
)
undated = ledger.entries(f"## Open questions / handoffs\n\n**[A {A} B]** - no date here\n")[0]
check(
    "an undated one has none, so the post takes the time of the import",
    migrate.created_of(undated[0]),
    None,
)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

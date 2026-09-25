# Security Policy

## Reporting a Vulnerability

Please report security issues privately using
[GitHub Security Advisories](https://github.com/teerakarna/session-exchange/security/advisories/new)
for this repository, rather than opening a public issue.

If you cannot use Security Advisories, email 21040807+teerakarna@users.noreply.github.com with a
description of the issue and steps to reproduce.

Please do not disclose publicly until it has been addressed.

## Scope

session-exchange runs automatically, as a hook, at the start and end of every Claude Code session in a
marked tree, and it writes files into that tree. Nothing here is privileged and there is no network
egress at all, but "code that runs unprompted and writes to your repos" is the honest description of
the surface, and it sets the threat model.

Most serious first.

### Cross-root leakage is the primary concern

Sessions are separated by root, and a root never reads another's sessions or handoffs, in either
direction. That boundary is the whole reason the tool is usable in an environment where some trees must
not learn anything about others. A bug that lets one root render, match or import from another is a
vulnerability and not a correctness nit, because the information it moves is exactly the information
somebody separated on purpose.

Two things defend it. Root resolution stops at the *nearest* marked ancestor, so a nested root resolves
inward and never widens. And `exchange init` refuses a directory whose sibling children are themselves
workspaces rather than repos, since marking that one directory would silently merge two trees that are
meant to stay apart. `--force` exists, prints the reason it is refusing, and is the only way past.

### The injected context is an untrusted channel

Claims and handoffs are written by other sessions and rendered into your session's context at
startup. Treat that text as data to display, never as instructions to follow. A claim's `focus` field
is somebody else's prose arriving inside your prompt, which is prompt injection with a friendly name,
and the reason `max_focus_chars` exists is to bound it rather than to tidy the output.

The same applies in the other direction: `/exchange` is documented as never claiming on the user's
behalf unasked and never hand-editing state.

### Identifiers are filenames

A session id is also the name of the file its claim lives in. `safe_id` refuses anything outside
`[A-Za-z0-9._-]` rather than sanitising it, which is deliberate: quietly rewriting an identifier is how
two sessions end up sharing one file, and a rejection is at least honest. Path traversal via a crafted
session id is the thing that check exists to stop.

### Writes

Every write validates against the schema first, then goes to a temp file in the same directory and
`os.replace`, which is atomic on the same filesystem. A reader therefore sees the old file or the new
one and never half of either, and an invalid file never reaches disk at all.

Nothing is created implicitly. With no marked root the plugin writes nothing, says nothing, and exits
0.

### No network, no telemetry, no daemon

There is no egress of any kind, no update check and no analytics. A change that adds any is a
vulnerability, not a feature. Everything runs as a short-lived subprocess of the session that spawned
it; there is no listening port and nothing in the background.

### The dependency surface is empty on purpose

The runtime imports the standard library and nothing else, and CI fails the build if that changes. A
hook that runs on every session start is a bad place to have a supply chain.

### What it reads that is not its own

`~/.claude/sessions/*.json`, the native session registry, for display names and liveness. Read-only,
never written. `~/.claude/settings.json` and `settings.local.json` files under the root, to detect a
legacy hook still wired: that scan reports the settings path and the bare script name only, and
deliberately never the command string, because a command string is where somebody's arguments are.

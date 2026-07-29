# CLI JSON protocol v1

Status: alpha contract.

This document defines tmt's machine-facing CLI protocol. tmt adopts the aiq
cli-v1 conventions wholesale — one protocol across aiq, tmt, and every
generated tool — but this document is self-contained.

## Common rules

- Every command except `tmt context` accepts `--json` after the subcommand
  (`context` emits session context that is injected, not parsed, and is
  plain text by design). With `--json`, success
  is exactly one compact, key-sorted UTF-8 JSON object followed by one newline
  on standard output; nothing else is written to standard output.
- Success uses standard output only. Failure uses standard error only.
- Every JSON result contains top-level integer `"v": 1`.
- With `--json`, every failure is one compact key-sorted object on standard
  error: `{"code": ..., "error": ..., "status": "error", "v": 1}`. Invocation
  errors (unknown command, missing argument) honor `--json` when it appears
  anywhere on the command line. See [errors.md](errors.md).
- Object consumers ignore unknown fields. Required field removal or changed
  meaning requires a new protocol version.
- Digests are lowercase SHA-256 hex. Human-readable output is terminal-safe
  (control characters escaped) but is not versioned.
- `tmt --version` prints the distribution version and exits 0; it has no JSON
  form.

## Registry discovery

Except for `init`, commands that touch the registry resolve the repo root as
the nearest directory at or above the working directory containing `tmt.json`,
and fail with `no-registry` (exit 3) when none exists. `tmt init` writes into
the current directory unconditionally. `tmt note` and `tmt candidates` do not
require a registry; when one is found, its root becomes the working directory
passed to aiq for scope resolution. `tmt integration` never touches the
registry, and `tmt context` resolves it the same way but silently exits 0
instead of failing when there is none.

## Command results

The tables list fields in addition to top-level `v`.

| Command | Success fields |
|---|---|
| `init --json` | `status: "initialized"`, absolute `path`, `stanza`; with `--agents` also `agents` (the `agents --write` result) |
| `agents --json` | `status`, absolute `path`, `fragment_version`; with `--write` also `changed`, `previous` |
| `integration print agents --json` | `fragment`, `fragment_version` |
| `integration print hook claude --json` | `fragment` (the settings.json hooks fragment object) |
| `integration plan claude --json` | `changed`, `entry`, `settings`, `status` |
| `integration install claude --json` | `status: "installed"`, `changed`, `entry`, `manifest`, `settings` |
| `integration check claude --json` | `status: "ok"`, `"absent"`, or `"drifted"`, `settings` |
| `integration uninstall claude --json` | `status: "uninstalled"`, `changed`, `removed`, `settings` |
| `new ID --json` | `id`, `lang`, repo-relative `path` and `test_path`, `stage: "draft"` |
| `list --json` | `tools`: array of `{id, purpose, stage}`, id ascending |
| `show ID --json` | `id`, `entry`, `help`, `doc` |
| `check --json` | `status: "ok"` or `"failed"`, `failures`, `warnings` |
| `stage ID STAGE --json` | `id`, `previous`, `stage`, `changed` |
| `note SLUG --json` | `slug`, `message_id`, `created`, optional `count` |
| `candidates --json` | `candidates`: array of `{count, notes, slug}` |
| `vendor SOURCE ID --json` | `status: "vendored"`, `id`, `origin`, repo-relative `path`, `config` when the entry declares any |
| `adopt ID --to DEST --json` | `status: "adopted"`, `id`, `origin`, absolute `to`, `config` when the entry declares any |

## init

```text
tmt init [--agents] [--json]
```

Creates an empty registry (`{"tools": {}, "v": 1}`) in the current directory.
Human output is the two-line `AGENTS.md` stanza; the JSON `stanza` field is
the same two strings as an array. An existing `tmt.json` is `already-exists`
(exit 3). With `--agents` it also installs the AGENTS.md fragment block
exactly as `tmt agents --write` would (the human output gains an
`AGENTS.md: installed` line; JSON gains `agents`).

## agents

```text
tmt agents [--write] [--json]
```

Reports the habit fragment's status in this repo's `AGENTS.md`:
`installed`, `stale` (block differs from the current render, malformed
included), `absent` (file without markers), or `no-agents-file`. With
`--write`, creates `AGENTS.md` or idempotently inserts/replaces the owned
marker block (`changed`, `previous` report what happened); a malformed block
(begin marker without end marker) is refused with `check-failed` (exit 3).
Human output is the status word, or `AGENTS.md: PREVIOUS -> installed` /
`AGENTS.md already installed` with `--write`. Fragment text, marker grammar,
and the matching `tmt check` gate are in
[integration-v1.md](integration-v1.md). No registry is `no-registry`
(exit 3).

## context

```text
tmt context
```

The SessionStart hook payload: plain text only, no `--json`. Prints the
repo's tool list and noted-candidate counts, capped at 40 lines; prints
nothing without a registry. Consumes and ignores stdin. Always exits 0 —
fail-open on every error path is a hard requirement of
[integration-v1.md](integration-v1.md).

## integration

```text
tmt integration print agents [--json]
tmt integration print hook claude [--json]
tmt integration {plan,install,check,uninstall} claude [--user] [--json]
```

`print agents` emits the canonical AGENTS.md fragment (`fragment`,
`fragment_version`); `print hook claude` emits the settings.json hooks
fragment for externally managed configuration. Both change nothing.

The lifecycle commands manage one tmt-owned `SessionStart` hook entry in the
user-level Claude Code `settings.json` (`--user` is the default and only
scope) with an ownership manifest: `plan` previews without writing,
`install` is idempotent (`changed: false` when already installed), `check`
reports `ok` (exit 0) / `absent` / `drifted` (exit 1, status on stdout, no
error envelope), and `uninstall` removes only the unmodified owned entry
plus any containers it created. An externally edited owned entry is refused
with `drift` (exit 3) by `install` and `uninstall`. Entry shape, manifest
format, merge guarantees, and drift semantics are in
[integration-v1.md](integration-v1.md).

## new

```text
tmt new ID [--lang {python,sh}] [--purpose TEXT] [--usage TEXT] [--json]
```

Scaffolds executable `tools/ID` (mode 0755) from the packaged template, an
executable born-passing POSIX sh smoke test `tools/ID.test` (invokes its
sibling by resolved path and asserts only that `--help` exits 0 — the sole
universal guarantee — plus a commented-out skeleton for real assertions:
sandbox with cleanup, `--json` line checks, and the check-style
expected-exit-1 pattern), and adds a fully explicit draft entry to
`tmt.json`. The stable gate refuses to promote while the test is the
unmodified scaffold (see [registry-v1.md](registry-v1.md)). Defaults: `--lang python`; purpose
`TODO: describe ID`; usage `tools/ID [--json]`. Purpose and usage are
collapsed to single lines; a purpose over 80 characters, an ID not matching
`^[a-z0-9][a-z0-9-]*$`, or an unsupported lang is `usage` (exit 2). An ID
already registered, or a `tools/ID` file already present, is `already-exists`
(exit 3). The scaffolded entry sets `json: true` because both templates ship a
working `--json` stub. Human output is the repo-relative tool path, then the
repo-relative test path, one per line.

## list

```text
tmt list [--json]
```

One tool per line, id ascending: `id`, `stage`, `purpose`, tab-separated.

## show

```text
tmt show ID [--json]
```

`entry` is the effective entry with schema defaults filled in. `help` is the
captured standard output of `tools/ID --help`, or `null` when the file is
missing or `--help` fails. `doc` is the content of `tools/ID.md`, or `null`
when absent. Human output is `key<TAB>value` lines for the sorted effective
entry (`config` and `requires` comma-joined; an origin object as
`repo@commit`), then each
non-null block separated by a blank line. An unregistered ID is `not-found`
(exit 3).

## check

```text
tmt check [--json]
```

Runs the full gate battery and collects every failure; see
[registry-v1.md](registry-v1.md) for the gates and
[vendoring-v1.md](vendoring-v1.md) for the drift warning. Exit 0 when there
are no failures, 1 otherwise; warnings never change the exit code. Human
output is one `FAIL ` line per failure and one `WARN ` line per warning,
then `ok` on success. A registry that is missing, unparseable, or invalid is
reported as `registry: `-prefixed failures (exit 1), and no tool gates run.

## stage

```text
tmt stage ID {draft,stable} [--json]
```

Promotes or demotes `ID` by rewriting `tmt.json` through the registry
serializer — the supported alternative to hand-editing `stage`. Promotion to
`stable` first runs that tool's full stable gate battery (the per-tool draft
gates, the undeclared-composition gate, and the stable gates from
[registry-v1.md](registry-v1.md)); any failure is `check-failed` (exit 3)
with every failing gate listed in `error`, and nothing is written. Demotion
to `draft` is `check-failed` (exit 3) while any stable tool `requires` `ID`.
A tool already at the requested stage is a reported no-op: exit 0 with
`changed: false` (human: `ID already STAGE`). On change the human output is
`ID: PREVIOUS -> STAGE`. An unregistered ID is `not-found` (exit 3); a
`STAGE` other than `draft` or `stable` is `usage` (exit 2).

## note

```text
tmt note SLUG [--note TEXT] [--json]
```

Emits one tool-candidate event through `aiq ingest --event-json -`. The event
is the canonical provider-neutral v1 envelope with `source: "tmt"`, an
absolute `cwd`, and `content` set to the compact key-sorted JSON object
`{"kind": "tmt-note", "note": TEXT-or-null, "slug": SLUG}`. `SLUG` must match
the tool-id pattern but need not be registered. `created` and `message_id`
are relayed from aiq's ingest receipt. After a successful ingest, tmt counts
this slug's notes through the same machinery as `candidates` and reports the
count: JSON gains an integer `count`, and the human output adds a second
line after the message id — `N notes for 'SLUG'`, extended with
`` — consider `tmt new SLUG` `` once the count reaches 2. Counting is
best-effort: if it fails after a successful ingest, the command still
succeeds with `count` omitted (and no second human line). aiq missing from
`PATH`, exiting nonzero, exceeding 30 seconds, or returning unparseable
output during the ingest itself is `aiq-unavailable` (exit 3).

## candidates

```text
tmt candidates [--json]
```

Reads `aiq inbox list --json --include-content --limit 1000` and groups the
messages whose `source` is `"tmt"` and whose content parses as a
`"kind": "tmt-note"` payload. Each group carries the `slug`, the occurrence
`count`, and the non-empty `notes`, ordered count descending then slug
ascending. Human output is `count<TAB>slug` lines. Failure classification
matches `note`.

## vendor

```text
tmt vendor SOURCE_REPO ID [--json]
```

Copies `tools/ID` (plus `tools/ID.md` and `tools/ID.test` when present, with
modes) from `SOURCE_REPO` into the current repo and writes the source entry
into `tmt.json` with `origin` stamped `{commit, repo, sha256}` plus `url`
when the source has an `origin` remote. Overwrites an
existing local copy deliberately. When the entry declares `config`, the
declared files are not copied; the human output adds a
`note: reads <paths>; create them in this repo` line and the JSON result
gains the `config` array. A source without `tmt.json` is
`no-registry`; a source without the entry or the file is `not-found` (both
exit 3).

## adopt

```text
tmt adopt ID --to DEST_REPO [--json]
```

The reverse of `vendor`: portability-lints the local tool, then copies it
(and companions) into `DEST_REPO`, stamping `origin` with this repo as the
source (including `url` when this repo has an `origin` remote). Only stable
tools can be adopted — hardening precedes trusting — so a non-stable `ID` is
`portability` (exit 3). Lint findings — a hardcoded `/home/` or this repo's
own absolute path in the tool body, or a `requires` entry not already
registered in the destination — are `portability` (exit 3) and nothing is
copied. A destination without `tmt.json` is `no-registry` (exit 3). When the
entry declares `config`, the declared files are not copied; the human output
adds a `note: reads <paths>; create them in the destination repo` line and
the JSON result gains the `config` array. Adoption
is mechanical preparation; promotion is the human committing the result in
the destination.

See [errors.md](errors.md) for failure classification and the
[registry contract](registry-v1.md) for `tmt.json` itself.

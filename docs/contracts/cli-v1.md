# CLI JSON protocol v1

Status: alpha contract.

This document defines tmt's machine-facing CLI protocol. tmt adopts the aiq
cli-v1 conventions wholesale — one protocol across aiq, tmt, and every
generated tool — but this document is self-contained.

## Common rules

- Every command accepts `--json` after the subcommand. With `--json`, success
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
passed to aiq for scope resolution.

## Command results

The tables list fields in addition to top-level `v`.

| Command | Success fields |
|---|---|
| `init --json` | `status: "initialized"`, absolute `path`, `stanza` |
| `new ID --json` | `id`, `lang`, repo-relative `path` and `test_path`, `stage: "draft"` |
| `list --json` | `tools`: array of `{id, purpose, stage}`, id ascending |
| `show ID --json` | `id`, `entry`, `help`, `doc` |
| `check --json` | `status: "ok"` or `"failed"`, `failures`, `warnings` |
| `stage ID STAGE --json` | `id`, `previous`, `stage`, `changed` |
| `note SLUG --json` | `slug`, `message_id`, `created`, optional `count` |
| `candidates --json` | `candidates`: array of `{count, notes, slug}` |
| `vendor SOURCE ID --json` | `status: "vendored"`, `id`, `origin`, repo-relative `path` |
| `adopt ID --to DEST --json` | `status: "adopted"`, `id`, `origin`, absolute `to` |

## init

```text
tmt init [--json]
```

Creates an empty registry (`{"tools": {}, "v": 1}`) in the current directory.
Human output is the two-line `AGENTS.md` stanza; the JSON `stanza` field is
the same two strings as an array. An existing `tmt.json` is `already-exists`
(exit 3).

## new

```text
tmt new ID [--lang {python,sh}] [--purpose TEXT] [--usage TEXT] [--json]
```

Scaffolds executable `tools/ID` (mode 0755) from the packaged template, an
executable born-passing POSIX sh smoke test `tools/ID.test` (resolves its
sibling via `dirname "$0"`, asserts `--help` exits 0 and that `--json` emits
one line holding one JSON object with `"v": 1`), and adds a fully explicit
draft entry to `tmt.json`. Defaults: `--lang python`; purpose
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
entry (`requires` comma-joined; an origin object as `repo@commit`), then each
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
existing local copy deliberately. A source without `tmt.json` is
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
copied. A destination without `tmt.json` is `no-registry` (exit 3). Adoption
is mechanical preparation; promotion is the human committing the result in
the destination.

See [errors.md](errors.md) for failure classification and the
[registry contract](registry-v1.md) for `tmt.json` itself.

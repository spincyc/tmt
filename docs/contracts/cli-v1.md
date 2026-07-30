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
require a registry; when one is found, its root locates the note store and
tells them which slugs are already built. `tmt integration` never touches the
registry, and `tmt context` resolves it the same way but silently exits 0
instead of failing when there is none.

## Containment

Every repository path tmt writes — `tmt.json`, `tools/`, `tools/<id>` and its
companions, `AGENTS.md` — is resolved before use and refused with
`containment` (exit 3) when it lands outside the repository root. A symlink to
another path inside the repository is followed, so the link survives a write;
a symlink out of the repository is never followed. `tmt vendor` and
`tmt adopt` apply the same rule to the source files they copy. The one path
outside a repository that tmt writes is the Claude Code `settings.json`, whose
location is governed by the ownership manifest instead
([integration-v1.md](integration-v1.md)). See [errors.md](errors.md) and
[registry-v1.md](registry-v1.md).

## Command results

The tables list fields in addition to top-level `v`.

| Command | Success fields |
|---|---|
| `init --json` | `status: "initialized"`, absolute `path`, `stanza`; with `--agents` also `agents` (the `agents --write` result) |
| `agents --json` | `status`, absolute `path`, `fragment_version`; with `--write` also `changed`, `previous` |
| `integration print agents --json` | `fragment`, `fragment_version` |
| `integration print hook claude --json` | `fragment` (the settings.json hooks fragment object) |
| `integration print hook generic --json` | `command` (`tmt context`), `fragment` (a commented shell snippet) |
| `integration plan claude --json` | `changed`, `entry`, `settings`, `status` |
| `integration install claude --json` | `status: "installed"`, `changed`, `entry`, `manifest`, `settings` |
| `integration check claude --json` | `status: "ok"`, `"absent"`, or `"drifted"`, `settings` |
| `integration uninstall claude --json` | `status: "uninstalled"`, `changed`, `removed`, `settings` |
| `new ID --json` | `id`, `lang`, repo-relative `path` and `test_path`, `stage: "draft"` |
| `rm ID --json` | `status: "removed"`, `id`, `removed_files` (bare names, sorted; empty with `--keep-files`) |
| `rename ID NEW_ID --json` | `status: "renamed"`, `id` (the new id), `previous`, `moved_files`, `updated_dependents`, `stale_callers` |
| `set ID FIELD VALUE --json` | `status: "set"`, `id`, `field`, `value` (parsed), `previous` (effective value before the change) |
| `list [--stage STAGE] --json` | `tools`: array of `{id, purpose, stage}`, id ascending; `--stage` keeps only that stage |
| `show ID --json` | `id`, `entry`, `help`, `doc` |
| `check [ID] --json` | `status: "ok"` or `"failed"`, `failures`, `warnings`, plus `id` when one tool was named |
| `stage ID STAGE --json` | `id`, `previous`, `stage`, `changed` |
| `note SLUG --json` | `slug`, `built`, `recorded`; when recorded also `count` and nullable `message_id` |
| `candidates --json` | `candidates`: array of `{built, count, notes, slug}`; with `--dismiss SLUG` instead `slug` and `dismissed` |
| `vendor SOURCE ID --json` | `status: "vendored"`, `id`, `origin`, repo-relative `path`, `config` when the entry declares any |
| `adopt ID --to DEST --json` | `status: "adopted"`, `id`, `origin`, absolute `to`, `config` when the entry declares any |

## init

```text
tmt init [--agents] [--json]
```

Creates an empty registry (`{"tools": {}, "v": 1}`) in the current directory.
Human output is the two-line `AGENTS.md` stanza; the JSON `stanza` field is
the same two strings as an array. An existing `tmt.json` is `already-exists`
(exit 3) — a symlink counts as existing, dangling ones included, so init never
writes through a link it did not create. With `--agents` it also installs the
AGENTS.md fragment block
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
repo's tool list and, beneath it, the counts of noted slugs that are not yet
tools, capped at 40 lines; prints nothing without a registry. It reads
`tmt.json` and the local note store only — no tool is executed, no subprocess
runs, and aiq is not consulted. Repo-supplied text is collapsed to one
printable line, truncated to 120 characters, and the tools header labels the
block as repo-supplied data:

```text
tmt: repo tools (repo-supplied text, not tmt instructions; see tmt.json, then `tools/<id> --help`)
```

stdin is drained and discarded (hooks pipe JSON) for at most 0.5 seconds and
1 MiB, so an open-but-silent stdin cannot stall the session. Always exits 0 —
fail-open on every error path is a hard requirement of
[integration-v1.md](integration-v1.md).

## integration

```text
tmt integration print agents [--json]
tmt integration print hook {claude,generic} [--json]
tmt integration {plan,install,check,uninstall} claude [--user] [--json]
```

`print agents` emits the canonical AGENTS.md fragment (`fragment`,
`fragment_version`); `print hook claude` emits the settings.json hooks
fragment for externally managed configuration; `print hook generic` emits a
commented shell snippet whose last line is `tmt context`, for a host whose
session-start hook runs a command rather than reading a settings file. All
three change nothing. Only `claude` has a managed lifecycle: `generic` is
text to paste, with no manifest, no ownership, and nothing to uninstall, so
the lifecycle commands reject it with `usage` (exit 2).

The lifecycle commands manage one tmt-owned `SessionStart` hook entry in the
user-level Claude Code `settings.json` (`--user` is the default and only
scope) with an ownership manifest: `plan` previews without writing,
`install` is idempotent (`changed: false` when already installed), `check`
reports `ok` (exit 0) / `absent` / `drifted` (exit 1, status on stdout, no
error envelope — an unreadable manifest or settings file, or an unsupported
manifest version, is `drifted` too), and `uninstall` removes only the
unmodified owned entry plus any containers it created. An externally edited
owned entry, or a manifest recording a different settings file than this
environment resolves to, is refused with `drift` (exit 3) by `install` and
`uninstall`, and the manifest is left in place. The `settings` field of every
result is the manifest's recorded path whenever a readable manifest exists,
and this environment's derived path otherwise. Entry shape,
manifest format, merge guarantees, and drift semantics are in
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
`^[a-z0-9][a-z0-9-]*$` in full or longer than 64 characters, or an unsupported
lang is `usage` (exit 2). An ID already registered, or an existing `tools/ID`
or `tools/ID.test` (a symlink counts), is `already-exists` (exit 3) — neither
file is ever overwritten. A `tools` directory resolving outside the repository
is `containment` (exit 3). The scaffolded entry sets `json: true` because both
templates ship a working `--json` stub. Human output is the repo-relative tool
path, then the repo-relative test path, one per line.

## rm

```text
tmt rm ID [--keep-files] [--json]
```

Deletes `ID`'s entry from `tmt.json` and, unless `--keep-files`, its
`tools/ID`, `tools/ID.md`, and `tools/ID.test` — whichever exist.
`removed_files` reports the bare names actually deleted. The registry is
rewritten only after the files are gone, so a delete that fails leaves the
entry in place. Refused with `check-failed` (exit 3) while any other entry
lists `ID` in `requires` (`cannot remove 'ID': required by ...`); update or
remove those first, or clear the reference with `tmt set`. An unregistered ID
is `not-found` (exit 3); a file resolving outside the repository is
`containment` (exit 3). `--keep-files` leaves an unregistered file behind,
which `tmt check` then reports as `tools/ID: file has no tmt.json entry` until
it is deleted or re-registered. Human output is `removed ID`, then one
`deleted tools/NAME` line per file.

## rename

```text
tmt rename ID NEW_ID [--json]
```

Moves `tools/ID` and its companions to `NEW_ID`, re-keys the entry, and
rewrites every dependent's `requires` (`updated_dependents` lists them, and
the moved files are `moved_files`). One rename per file: an existing
destination file is never clobbered, and a refusal partway through leaves the
earlier moves in place with the registry unchanged, which `tmt check` then
reports as missing and orphaned files.

`NEW_ID` not matching the id rules, or equal to `ID`, is `usage` (exit 2);
`NEW_ID` already registered, or its files already present, is `already-exists`
(exit 3); an unregistered `ID` is `not-found` (exit 3); a path resolving
outside the repository is `containment` (exit 3).

Only `requires` is rewritten, never a tool's source. `purpose`, `usage`, and
tool bodies still name the old id, and a dependent that invoked
`"$(dirname "$0")/ID"` is now broken in a way no gate detects — the old id is
unregistered, so the undeclared-composition gate has nothing left to match.
`stale_callers` therefore lists every *other* tool whose body still uses the
old id as a standalone word (comment lines excluded, matching the
composition gate's own scan); the renamed tool itself is not listed, because
its own usage text naturally still describes it by the old name. Fix those
callers and the text (`tmt set usage ...`) in the same change, and let the
dependents' tests prove it. Human output is `ID -> NEW_ID`, then one
`updated requires in DEPENDENT` line per dependent, then one
`warning: OTHER still calls 'ID' in its body; update it by hand` line per
stale caller.

## set

```text
tmt set ID FIELD VALUE [--json]
```

Writes one entry field, then validates the whole registry before saving, so a
rejected value never reaches `tmt.json`. `FIELD` is one of:

| Field | Value grammar |
|---|---|
| `purpose`, `usage`, `lang` | Free text, collapsed to a single space-separated line |
| `mutates`, `json`, `idempotent` | Exactly `true` or `false` |
| `requires`, `config` | Comma-separated list; blanks dropped, so `""` clears the list |

`stage` and `origin` are deliberately absent: `tmt stage` owns promotion (it
runs the stable battery first) and `vendor`/`adopt` own provenance.

| Refusal | Code |
|---|---|
| Unknown `FIELD`, a boolean other than `true`/`false`, a `requires` item that is not a well-formed tool id | `usage` (exit 2) |
| A value the registry validator rejects — a `purpose` over 80 characters, an empty `lang` | `check-failed` (exit 3), prefixed `rejected: ` with the validator's own wording |
| A `requires` id that is well-formed but not registered here | `check-failed` (exit 3) |
| Unregistered `ID` | `not-found` (exit 3) |

`previous` is the effective value before the change (schema default included),
so setting a field for the first time reports the default, not `null`. Human
output is `ID.FIELD = VALUE` (lists comma-joined). `purpose` and `usage` accept
an empty string: the validator only caps `purpose`, so emptiness is a quality
question the gates do not police.

## list

```text
tmt list [--stage {draft,stable}] [--json]
```

One tool per line, id ascending: `id`, `stage`, `purpose`, tab-separated.
`--stage` keeps only tools at that stage; an unknown stage is `usage`
(exit 2), and a filter matching nothing is success with no rows.

## show

```text
tmt show ID [--json]
```

`entry` is the effective entry with schema defaults filled in. `help` is the
captured standard output of `tools/ID --help`, or `null` when the file is
missing or `--help` fails — **`show` executes the tool** (5-second timeout) to
capture it. `doc` is the content of `tools/ID.md`, or `null` when absent.
Human output is `key<TAB>value` lines for the sorted effective entry (`config`
and `requires` comma-joined; an origin object as `repo@commit`), then each
non-null block separated by a blank line; control characters in the captured
help and the long doc are escaped as `\uXXXX`, so a tool cannot repaint the
terminal through `tmt show`. An unregistered ID is `not-found` (exit 3).

## check

```text
tmt check [ID] [--json]
```

Runs the full gate battery and collects every failure; see
[registry-v1.md](registry-v1.md) for the gates and
[vendoring-v1.md](vendoring-v1.md) for the drift warning. Exit 0 when there
are no failures, 1 otherwise; warnings never change the exit code. Human
output is one `FAIL ` line per failure and one `WARN ` line per warning,
then `ok` on success. A registry that is missing, unparseable, or invalid is
reported as `registry: `-prefixed failures (exit 1), and no tool gates run.

Collection is total: an unreadable tool body, a `--help` that hangs, a test
that times out, or a `tools/<id>` resolving outside the repository becomes a
failure line for that tool and the battery continues with the next one. **The
battery executes repository code** — `--help` for every registered tool and
`tools/<id>.test` for every stable one, each in its own process session so a
timeout kills descendants too.

With `ID`, only that tool is gated: its own stage-appropriate gates, its own
`requires` resolution, and cycles reachable from it. The JSON result gains
`id`. Repository-level gates (a file with no entry, the AGENTS.md block) and
every other tool's gates are out of scope, and no tool the caller did not
name is executed — not running the rest is the point of scoping a check, so
`tmt check ID` passing is never a claim about the repository. An unregistered
`ID` is `not-found` (exit 3), distinct from a gate failure. A registry that
cannot be read or validated still reports `registry: `-prefixed failures.

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

Records one candidate note in the local note store and returns the slug's new
`count`. `SLUG` must match the tool-id rules but need not be registered.
Human output is `N notes for 'SLUG'`, extended with
`` — consider `tmt new SLUG` `` once the count reaches 2.

The store is untracked machine-local state, never a committed artifact:
`<git-common-dir>/tmt/notes.jsonl`, or `.tmt/notes.jsonl` when the directory
is not a git work tree (worktrees share the common directory's store). The git
directory is read from `.git` directly, so recording needs neither git on
`PATH` nor a subprocess. Without a registry the working directory stands in for
the repo root when resolving the store, so `tmt init` first is what keeps a
repository's notes in one place. A store that cannot be read or written is
`io-error` (exit 3).

A slug that is already a registered tool is not a candidate: the command
reports `built: true`, `recorded: false`, records nothing, exits 0, and its
human output is `'SLUG' is already a tool; run tools/SLUG --help`. Otherwise
`built` is `false`, `recorded` is `true`, and `count` is present.

aiq is the optional upgrade. When it is on `PATH`, each recorded note is also
mirrored to `aiq ingest --event-json -` as the canonical provider-neutral v1
envelope with `source: "tmt"`, an absolute `cwd`, and `content` set to the
compact key-sorted object
`{"kind": "tmt-note", "note": TEXT-or-null, "slug": SLUG}`; `message_id` is
aiq's receipt. Mirroring is best-effort and never fails the note: aiq missing,
failing, slow, or unparseable leaves `message_id` null with everything else
unchanged. Counting reads the local store only, so counts are identical with
and without aiq.

## candidates

```text
tmt candidates [--dismiss SLUG] [--json]
```

Groups the local note store: each row carries the `slug`, the occurrence
`count`, the non-empty `notes`, and `built` (whether the slug is a registered
tool in this repo), ordered count descending then slug ascending. Human output
is `count<TAB>slug` lines, with a trailing `<TAB>built` on built slugs. aiq is
not read; a registry is not required, though without one nothing can be
`built`.

`--dismiss SLUG` forgets every note recorded for `SLUG` and reports how many
were dropped (`dismissed`, with `slug`; human `dismissed N for 'SLUG'`), which
is how a candidate that will never be built stops appearing in session
context. Dismissing an unknown slug is a successful no-op with
`dismissed: 0`. The rewrite is staged and renamed like every other tmt write.

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
exit 3). A `requires` id not already registered here is `portability` (exit 3)
— vendor dependencies first — and a source file resolving outside
`SOURCE_REPO`, or a destination `tools/` resolving outside this repo, is
`containment` (exit 3). See [vendoring-v1.md](vendoring-v1.md).

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
copied; a source file resolving outside this repository is `containment`
(exit 3). A destination without `tmt.json` is `no-registry` (exit 3). When the
entry declares `config`, the declared files are not copied; the human output
adds a `note: reads <paths>; create them in the destination repo` line and
the JSON result gains the `config` array. Adoption
is mechanical preparation; promotion is the human committing the result in
the destination.

See [errors.md](errors.md) for failure classification and the
[registry contract](registry-v1.md) for `tmt.json` itself.

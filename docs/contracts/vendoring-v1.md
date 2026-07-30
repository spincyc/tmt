# Vendoring v1

Status: alpha contract.

Tool movement between repos is symmetric copying with provenance — vendoring,
never linking. `tmt vendor` copies in; `tmt adopt` copies out. Both stamp the
destination entry's `origin` so drift is detectable, and both are ordinary
working-tree edits: nothing is committed for you, and promotion is the human
committing the result.

## What moves

Both directions copy, preserving file modes:

| File | When |
|---|---|
| `tools/<id>` | always |
| `tools/<id>.md` | when present in the source |
| `tools/<id>.test` | when present in the source |

The source registry entry is copied into the destination `tmt.json` with only
`origin` replaced. `stage`, `requires`, `config`, and every other field carry
over unchanged. Both source and destination must already be tmt-enabled
(`no-registry` otherwise); the moved tool must be registered and present in
the source (`not-found` otherwise).

Copying is contained in both repositories. The source `tools/<id>` and each
companion must resolve inside the source repository, and the destination
`tools/` directory must resolve inside the destination repository; anything
resolving outside is refused with `containment` (exit 3) instead of followed.
Without that rule an untrusted repository could register a symlink and have
tmt copy an arbitrary local file into your registry, staged for commit. Every
source — the executable and each companion — is resolved and checked before
the first byte is written, so a refusal copies nothing at all rather than
leaving a half-copied tool for `tmt check` to report.

Files listed in the entry's `config` are **not** copied — config is
repo-specific by nature. When the entry declares any, both commands remind
the consumer instead: the human output gains a
`note: reads <paths>; create them in this repo` line (`... in the
destination repo` for adopt), and the JSON result gains a `config` array.
The destination is expected to create those files before running the tool;
without them the copy fails at runtime.

## The origin stamp

| Field | Value |
|---|---|
| `repo` | Resolved absolute path of the source repository |
| `commit` | `git rev-parse HEAD` in the source, or `"unknown"` when Git or the repo is unavailable |
| `sha256` | SHA-256 of the copied executable (companions are not digested) |
| `url` | `git remote get-url origin` in the source; omitted when no `origin` remote is configured |
| `id` | The tool's id on the source side. Drift resolves `<repo>/tools/<id>` through this, so a local `tmt rename` keeps reporting drift; absent (older stamps) means the local id |

Tools born in place keep `origin: "local"`. The stamp records where a copy
came from; it grants nothing and is never consulted at runtime.

## vendor (copy in)

```text
tmt vendor SOURCE_REPO ID
```

Copies `ID` from `SOURCE_REPO` into the current repo. An existing local copy
and entry are overwritten: re-vendoring is the deliberate way to take the
source's newer version, discarding local divergence.

Two refusals apply before the entry is written:

| Finding | Rule |
|---|---|
| Unvendored dependency | Every `requires` id must already be registered in this repo — vendor dependencies first, leaves before roots (`portability`, exit 3), checked before anything is copied |
| Escaping source file | `tools/ID` and its companions must resolve inside `SOURCE_REPO` (`containment`, exit 3) |

The dependency rule mirrors `adopt`'s: a copy whose siblings are missing is
broken on arrival, and `tmt check` would fail the moment it lands.

## adopt (copy out)

```text
tmt adopt ID --to DEST_REPO
```

Refuses a non-stable tool, then runs the portability lint; either is
`portability` (exit 3) and nothing is copied:

| Finding | Rule |
|---|---|
| Unhardened tool | `stage` must be `"stable"` — hardening precedes trusting; promote with `tmt stage <id> stable` first |
| Hardcoded home path | Tool body must not contain `/home/` |
| Hardcoded repo path | Tool body must not contain this repo's own absolute path |
| Unpromoted dependency | Every `requires` id must already be registered in the destination — adopt dependencies first, leaves before roots |

The lint is textual and applies to the executable body only. A source file
resolving outside this repository is refused separately with `containment`
(exit 3). Adoption does not modify the source repo; the destination's human
approves the promotion by committing it.

## Drift and forking

Divergence after vendoring is allowed by design: per-repo fitness beats
shared-dependency correctness. Fork by editing the vendored copy in place;
the `origin` stamp keeps the ancestry inspectable.

`tmt check` surfaces drift as a warning, never a failure, and it is a
three-way comparison. `origin.sha256` is the content at vendoring time, so
it serves as the merge base against the local copy and the source's current
`<origin.repo>/tools/<id>`:

| Local vs base | Source vs base | Reported |
|---|---|---|
| same | same | nothing |
| **changed** | same | **nothing** — this is the sanctioned fork |
| same | changed | `WARN`: the source has a newer version; re-vendor to take it |
| changed | changed | `WARN`: both changed since vendoring; re-vendoring would discard the local changes |

Comparing only the source's current content against the local copy cannot
distinguish those middle two rows, so a purely local fork drew a warning
advising the one action — re-vendoring — that discards it.

A stable tool whose `origin.repo` is unreachable or deleted produces no
warning, and only stable tools are checked. Companions are not digested, so
an upstream change confined to `tools/<id>.test` is invisible here. The
remedies stay symmetric and deliberate: re-vendor to take the source's
version, or keep the fork.

`tmt rename` does not rewrite `origin`, and it does not need to: the source
path resolves through `origin.id`, so a renamed vendored tool keeps its drift
reporting. A stamp written before `origin.id` existed falls back to the local
id and loses drift on rename — re-vendor to refresh it.

Tools about tool-making graduate one step further — into tmt itself — by
ordinary pull request, not by vendoring. See
[concepts](../concepts.md#extraction-tiers) for the tier model.

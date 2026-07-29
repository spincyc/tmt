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
`origin` replaced. `stage`, `requires`, and every other field carry over
unchanged. Both source and destination must already be tmt-enabled
(`no-registry` otherwise); the moved tool must be registered and present in
the source (`not-found` otherwise).

## The origin stamp

| Field | Value |
|---|---|
| `repo` | Resolved absolute path of the source repository |
| `commit` | `git rev-parse HEAD` in the source, or `"unknown"` when Git or the repo is unavailable |
| `sha256` | SHA-256 of the copied executable (companions are not digested) |
| `url` | `git remote get-url origin` in the source; omitted when no `origin` remote is configured |

Tools born in place keep `origin: "local"`. The stamp records where a copy
came from; it grants nothing and is never consulted at runtime.

## vendor (copy in)

```text
tmt vendor SOURCE_REPO ID
```

Copies `ID` from `SOURCE_REPO` into the current repo. An existing local copy
and entry are overwritten: re-vendoring is the deliberate way to take the
source's newer version, discarding local divergence.

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

The lint is textual and applies to the executable body only. Adoption does
not modify the source repo; the destination's human approves the promotion
by committing it.

## Drift and forking

Divergence after vendoring is allowed by design: per-repo fitness beats
shared-dependency correctness. Fork by editing the vendored copy in place;
the `origin` stamp keeps the ancestry inspectable.

`tmt check` surfaces drift as a warning, never a failure: when a stable
tool's `origin.repo` is a readable local path and
`<origin.repo>/tools/<id>` differs from the local copy by sha256, check
emits one `WARN` line (JSON: an entry in `warnings`) and still exits 0. An
unreachable or deleted source produces no warning. The remedies are
symmetric and always deliberate: re-vendor to take the source's version, or
keep the fork and live with the warning.

Tools about tool-making graduate one step further — into tmt itself — by
ordinary pull request, not by vendoring. See
[concepts](../concepts.md#extraction-tiers) for the tier model.

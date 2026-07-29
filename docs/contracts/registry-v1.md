# Registry v1 (`tmt.json`)

Status: alpha contract.

`tmt.json` at the repository root is the single canonical registry: one
committed JSON object holding one manifest entry per tool. Tools are pure
executables under `tools/` — no comment-header grammar, no per-tool manifest
files. The normative structural schema is
[`schemas/tmt-v1.schema.json`](../../schemas/tmt-v1.schema.json)
(`additionalProperties: false`); tmt validates with a hand-rolled stdlib
mirror of it.

## Serialization

Writers emit `json.dumps(data, sort_keys=True, indent=2)` plus one trailing
newline. Key-sorting and one object per tool keep diffs clean and merge
conflicts rare; run `tmt check` as the post-merge fixup.

## Shape

```json
{
  "v": 1,
  "tools": {
    "changed-files": {
      "purpose": "List files changed vs merge-base, one per line",
      "usage": "tools/changed-files [--json] [BASE]",
      "stage": "stable",
      "lang": "python",
      "json": true,
      "mutates": false,
      "idempotent": true,
      "requires": [],
      "origin": "local"
    }
  }
}
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `v` (top level) | const `1` | yes | — | Registry format version |
| `tools` (top level) | object | yes | — | Entries keyed by tool id |
| `purpose` | string ≤ 80 chars | yes | — | One-line discovery summary |
| `usage` | string | yes | — | Invocation synopsis, e.g. `tools/<id> [--json]` |
| `stage` | `"draft"` or `"stable"` | yes | — | Lifecycle stage; see [concepts](../concepts.md) |
| `lang` | nonempty string | no | `"python"` | `"python"`, `"sh"`, or a recorded exception |
| `json` | boolean | no | `false` | Tool supports `--json` per cli-v1 |
| `mutates` | boolean | no | `false` | Tool changes state outside its own output |
| `idempotent` | boolean | no | `true` | Repeating the tool is safe |
| `requires` | array of tool ids | no | `[]` | Sibling tools this tool executes |
| `origin` | `"local"` or stamp object | no | `"local"` | Provenance; see [vendoring-v1.md](vendoring-v1.md) |

An origin stamp object has `repo` (nonempty source path), `commit` (source
commit, `"unknown"` when unresolvable), and `sha256` (64 lowercase hex
characters of the copied executable), plus an optional `url` (the source
repository's `origin` remote URL, recorded when one was configured at copy
time).

`mutates` and `idempotent` reuse aiq's capability-descriptor vocabulary; tmt
records them for readers and does not enforce them.

## Semantic rules beyond the schema

The schema is structural; `tmt check` enforces the rest. Every failure is
collected and reported, never just the first.

| Rule | Applies to | Enforced by |
|---|---|---|
| Tool id matches `^[a-z0-9][a-z0-9-]*$` and equals the filename `tools/<id>` | all | validator + check |
| Every entry has its file; every file has its entry (parity both directions) | all | check |
| `purpose` at most 80 characters — it is the per-session discovery cost | all | validator |
| Source lints: Python must compile; sh passes `sh -n`; other langs skipped | all | check |
| Executable bit set on `tools/<id>` | all | check |
| `tools/<id> --help` exits 0 within 5 seconds | all | check |
| Every `requires` id resolves; no duplicate ids; no dependency cycles | all | validator + check |
| Undeclared composition: another tool's id appearing as a standalone word in the body must be in `requires` | all | check |
| Executable `tools/<id>.test` exists and exits 0 within 60 seconds, run from the repo root | stable | check |
| Must not `require` a draft tool | stable | check |
| No hardcoded absolute paths: body contains neither `/home/` nor this repo's own absolute path | stable | check |
| Vendored copy differing from a readable `origin.repo` by sha256 | stable | check (warning only) |

Mentioning another registered tool's id in a tool body implies a dependency
and must be declared in `requires`. The gate reads each body as text
(undecodable files are skipped) and matches every other registered id as a
standalone word — no adjacent `[A-Za-z0-9_-]`, so ids embedded in longer
identifiers do not count. It applies to every stage, because an undeclared
composition breaks silently the moment the sibling is renamed or removed.

Files under `tools/` whose names start with `.` or end in `.md` or `.test`
are companions, not tools, and are exempt from parity. `tools/<id>.md` is the
optional long doc surfaced by `tmt show`; `tools/<id>.test` is the stable
gate's test.

Readers fill defaults when interpreting an entry (`tmt show` reports this
effective view). `tmt new` writes every field explicitly, including
`json: true`, because its scaffolds ship a working `--json` stub.

## Versioning

`v` is the format version and is currently always `1`. Registry input is
strict: unknown top-level keys, unknown entry keys, and unknown origin keys
are validation failures, so `tmt.json` is not a place for private extensions.

Within v1, the only compatible change is additive: a new optional field with
a default, or a new enum value, that leaves every existing registry valid.
Removing a field, changing a type or meaning, or adding a required field
requires `"v": 2`. Because validation is strict, a registry using a newer
additive field fails under an older tmt; keep the tmt release at least as new
as the newest field the repo uses.

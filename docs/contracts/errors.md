# CLI errors

Status: alpha contract.

tmt separates human diagnostics from stable machine classification, following
aiq's error conventions. Error messages may improve without changing the
error code.

## JSON form

With `--json`, every failure writes exactly one compact key-sorted JSON
object to standard error and writes nothing to standard output:

```json
{"code":"not-found","error":"tool 'x' is not registered in tmt.json","status":"error","v":1}
```

`v`, `status`, `code`, and `error` are required. `status` is always `error`.
`code` is stable machine-readable ASCII. `error` is a single-line,
terminal-safe human explanation. Consumers must ignore unknown fields.

Invocation errors (unknown command, missing argument) honor `--json` when it
appears anywhere on the command line. Unexpected defects use `internal`; JSON
mode never emits a traceback.

Outside JSON mode, tmt writes a single-line `tmt: `-prefixed diagnostic (or
`tmt COMMAND: ` for argparse invocation errors) to standard error. Human
wording is not a compatibility surface.

## Exit codes

| Exit | Category | Codes |
|---:|---|---|
| 0 | Success, including `tmt check` with warnings only | — |
| 1 | `tmt check` found failures (reported on stdout, no error envelope) | — |
| 2 | Invalid invocation or input value | `usage` |
| 3 | Repository, registry, or environment state rejects the operation | `not-found`, `already-exists`, `no-registry`, `check-failed`, `aiq-unavailable`, `portability` |
| 70 | Unexpected tmt implementation defect | `internal` |

The exit code is the coarse recovery category; `code` is the precise branch.
Automation should use both and must not parse `error`.

## Stable codes

| Code | Meaning |
|---|---|
| `usage` | CLI syntax, a tool id or slug, a lang, or a bounded value (purpose over 80 chars) is invalid |
| `not-found` | The named tool has no registry entry, or its `tools/<id>` file is missing |
| `already-exists` | `init` found an existing `tmt.json`; `new` found the id registered or the file present |
| `no-registry` | No `tmt.json` at or above the working directory, or in a vendor source / adopt destination |
| `check-failed` | A command had to load `tmt.json` and it does not parse or validate |
| `aiq-unavailable` | aiq is not on `PATH`, exited nonzero, timed out, or returned unusable output |
| `portability` | `adopt` lint findings: hardcoded absolute paths or unpromoted dependencies |
| `internal` | An uncategorized implementation defect escaped normal handling |

`check-failed` is raised by commands other than `tmt check` (exit 3); `tmt
check` itself never uses the error envelope for gate findings — it reports
them as `FAIL` lines (or the JSON `failures` array) and exits 1. `tmt note`
and `tmt candidates` are the only commands that can return
`aiq-unavailable`; every other command works without aiq.

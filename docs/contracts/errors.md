# CLI errors

Status: alpha contract. The error surface is part of
[CLI JSON protocol v1](cli-v1.md) and carries no separate version of its own:
a change here that breaks a consumer requires a new protocol version there.

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
appears anywhere on the command line. Environment failures — a file that
cannot be read, written, or renamed — use `io-error`; `internal` is reserved
for genuine implementation defects, and JSON mode never emits a traceback. A
committed artifact whose *content* is wrong (a `tmt.json` or `AGENTS.md` that
is not valid UTF-8, or a registry that does not validate) is `check-failed`
instead: that is repository state, not environment.

Outside JSON mode, tmt writes a single-line `tmt: `-prefixed diagnostic (or
`tmt COMMAND: ` for argparse invocation errors) to standard error. Human
wording is not a compatibility surface.

## Exit codes

| Exit | Category | Codes |
|---:|---|---|
| 0 | Success, including `tmt check` with warnings only, and every `tmt context` run | — |
| 1 | `tmt check` found failures; `tmt integration check` found the hook absent or drifted (reported on stdout, no error envelope) | — |
| 2 | Invalid invocation or input value | `usage` |
| 3 | Repository, registry, or environment state rejects the operation | `not-found`, `already-exists`, `no-registry`, `check-failed`, `aiq-unavailable`, `portability`, `drift`, `containment`, `io-error` |
| 70 | Unexpected tmt implementation defect | `internal` |
| 130 | Interrupted (`KeyboardInterrupt`); reported as `io-error` | `io-error` |

The exit code is the coarse recovery category; `code` is the precise branch.
Automation should use both and must not parse `error`.

## Stable codes

| Code | Meaning |
|---|---|
| `usage` | CLI syntax, a tool id or slug (pattern or the 64-character cap), a lang, a `tmt set` field or boolean, or a bounded value (purpose over 80 chars) is invalid |
| `not-found` | The named tool has no registry entry, or its `tools/<id>` file is missing |
| `already-exists` | `init` found an existing `tmt.json` (a symlink, dangling included, counts as existing); `new` found the id registered or `tools/<id>` or `tools/<id>.test` present; `rename` found the new id registered or its files present |
| `no-registry` | No `tmt.json` at or above the working directory, or in a vendor source / adopt destination |
| `check-failed` | A command had to load `tmt.json` and it does not parse or validate; `tmt stage` refused a promotion (stable gates failed) or a demotion (a stable tool requires the target); `tmt rm` refused to remove a tool another entry `requires`; `tmt set` produced an entry that fails validation or an unresolvable `requires`; `tmt agents --write` found a malformed marker block; or a managed integration settings or manifest file does not parse or validate |
| `aiq-unavailable` | aiq is not on `PATH`, exited nonzero, timed out, or returned unusable output. No command fails with it: `tmt note` mirrors to aiq best-effort and swallows it |
| `portability` | `adopt` refusals: a non-stable tool, hardcoded absolute paths, or dependencies not registered in the destination; `vendor` refusals: a dependency not registered here |
| `drift` | The integration's owned settings entry was edited or removed externally, or the ownership manifest records a different settings file than this environment resolves to; `install` and `uninstall` refuse rather than guess (see [integration-v1.md](integration-v1.md)) |
| `containment` | A path tmt would write, or a source file `vendor`/`adopt` would copy, resolves outside its repository root; tmt refuses to follow the link |
| `io-error` | An environment failure, not a tmt defect: a file cannot be read, written, renamed, or deleted (the note store included), or the run was interrupted (exit 130) |
| `internal` | An uncategorized implementation defect escaped normal handling |

`check-failed` is raised by commands other than `tmt check` (exit 3); `tmt
check` itself never uses the error envelope for gate findings — it reports
them as `FAIL` lines (or the JSON `failures` array) and exits 1, and `tmt
integration check` reports its status the same way. A registered tool whose
`tools/<id>` resolves outside the repository is one of those `FAIL` lines,
not a `containment` envelope.

No command requires aiq. `aiq-unavailable` remains a defined code — the
bridge still raises it internally — but `tmt note` mirrors to aiq
best-effort and reports success regardless, and `tmt candidates` reads only
the local note store. `tmt context` fails open to silence and never errors
at all.

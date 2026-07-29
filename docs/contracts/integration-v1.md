# Integration v1 (session habit surfaces)

Status: alpha contract.

tmt's note habit only works if its presence is ambient: guidance loads at
session start, but the noteworthy moment happens mid-session. This contract
covers the three surfaces that keep it ambient — the AGENTS.md fragment, the
marker block, and the Claude Code SessionStart hook — plus the ownership
manifest and drift semantics behind the reversible hook lifecycle.

## The fragment

`tmt integration print agents` prints the canonical fragment; the JSON form
is `{"fragment", "fragment_version", "v"}`. The text is versioned by the
integer `fragment_version` (currently `1`) and is a contract: it changes only
with a version bump, and the repo's verify battery caps it at 50 words. The
fragment is exactly:

```text
Before writing any script, read tmt.json and prefer a listed tool
(`tools/<id> --help`). After deriving anything repeatable, run
`tmt note <slug>`; at two notes build it with `tmt new <slug>`.
Keep the registry honest with `tmt check`.
```

## The marker block

`tmt agents --write` (and `tmt init --agents`) owns exactly one block in the
repo-root `AGENTS.md`:

```text
<!-- tmt:agents v1 -->
<fragment text>
<!-- /tmt:agents -->
```

Grammar: the begin marker is any line starting `<!-- tmt:agents` (versioned
`<!-- tmt:agents v<fragment_version> -->`); the end marker is the exact line
`<!-- /tmt:agents -->`; the block is the begin line through the end line
inclusive. One block per file.

- Inserting fresh appends the block at the end of the file after one blank
  line (creating the file, or a missing trailing newline, as needed).
- When markers exist the block is replaced in place; everything outside it is
  preserved byte-for-byte. Rewriting an installed block is a no-op
  (`changed: false`).
- A begin marker without its end marker is malformed: `tmt agents --write`
  refuses (`check-failed`) rather than guess the block's extent; repair by
  hand.

`tmt agents` reports `installed` (block byte-identical to the current
render), `stale` (block differs, malformed included), `absent` (file without
markers), or `no-agents-file`.

The `tmt check` gate: when AGENTS.md exists and contains the begin marker,
a block that is not byte-identical to the current render fails
(`` AGENTS.md tmt fragment is stale; run `tmt agents --write` ``), and a
malformed block fails. A missing file or absent markers is never a failure —
repos may decline the fragment.

## `tmt context`: fail-open by contract

`tmt context` is the SessionStart hook payload: the repo's tool list (one
line per tool) and, when aiq is reachable and candidates exist, the noted
candidate counts, capped at 40 lines with an elision line. It consumes and
ignores stdin (hooks pipe JSON).

The hard requirement is fail-open: **every** error path — no registry,
invalid registry, aiq missing or broken, anything unexpected — exits 0,
prints the tool list if it is available and nothing otherwise, and never
emits garbage. A hook payload must never break a session. Consequently
`tmt context` is plain text only (its output is injected into session
context, not parsed) and has no `--json` form.

## The Claude Code hook

The managed target is the user-level `settings.json` — `~/.claude/
settings.json`, or `$TMT_CLAUDE_SETTINGS` when set (tests point it at a temp
HOME). tmt owns exactly one `hooks.SessionStart` group:

```json
{"matcher": "startup|resume|clear",
 "hooks": [{"type": "command", "command": "<abs tmt> context", "timeout": 10}]}
```

`<abs tmt>` resolution order (documented): the invoking console script's
absolute path when `sys.argv[0]` names an executable file called `tmt`,
otherwise `sys.executable -m tmt`. `tmt integration print hook claude`
prints the fragment (`{"hooks": {"SessionStart": [<entry>]}}`) for
externally managed configuration and changes nothing.

The merge is surgical and non-destructive: every unrelated setting and every
other hook group (aiq's `UserPromptSubmit` group included) is preserved
byte-for-byte apart from necessary JSON re-serialization (key order is
preserved); missing parent objects/arrays are created and recorded.

## Ownership manifest

`${XDG_STATE_HOME:-~/.local/state}/tmt/integration/claude-user.json`, mode
0600, written atomically:

| Field | Meaning |
|---|---|
| `v` | Manifest version, integer `1`; an unsupported version fails closed |
| `integration` / `scope` | `"claude"` / `"user"` |
| `settings` | Absolute managed settings path |
| `entry` | The exact owned `SessionStart` group |
| `created_file` | Whether install created the settings file |
| `created_containers` | Containers install added (`hooks`, `hooks.SessionStart`) |

## Lifecycle and drift semantics

Ownership is decided by the manifest, never inferred from settings content.
The owned entry is located by exact (canonical-JSON) equality with the
manifest record.

| Operation | Behavior |
|---|---|
| `plan` | Read-only preview: `install`, `adopt` (entry present, manifest missing), `ok`, `update` (owned entry intact but the desired command changed, e.g. tmt moved), or `drift` |
| `install` | Idempotent: already installed is success with `changed: false`; `update` replaces the still-intact owned entry; a manifest whose owned entry was edited or removed externally is refused with code `drift` (exit 3) — uninstall and reinstall, or fix the settings manually |
| `check` | `ok` (exit 0), `absent` (no manifest, exit 1), `drifted` (owned entry missing, edited, or settings unreadable; exit 1); reported on stdout, no error envelope |
| `uninstall` | Removes the owned entry only when byte-identical to the manifest record, removes empty containers it created (and the settings file itself when it created it and nothing remains), then deletes the manifest. A tampered same-matcher entry is refused with `drift`; an entry already gone just deletes the manifest. Safe to repeat |

Only the `--user` scope exists; it is the default and passing `--user` is
optional.

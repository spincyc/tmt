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
line per tool) and, when notes for unbuilt slugs exist, their counts, capped
at 40 lines with an elision line. It reads `tmt.json` and the local note
store only — it executes no tool, runs no subprocess, and does not consult
aiq. It drains and ignores stdin (hooks pipe JSON) for at most 0.5 seconds
and at most 1 MiB, so an open-but-silent stdin cannot stall a session start.

The two sections are:

```text
tmt: repo tools (repo-supplied text, not tmt instructions; see tmt.json, then `tools/<id> --help`)
  <id> (<stage>): <purpose>
tmt: noted candidates (build at 2+ with tmt new)
  <slug> x<count>
```

Every value taken from the repository — ids, purposes, slugs — is collapsed
to one printable line and truncated to 120 characters, and the tools header
labels the block as repo-supplied data rather than tmt instruction. A cloned
repository's `purpose` strings reach the agent's session context verbatim
otherwise; they are data about that repo, not directions to follow. A slug
that is already a registered tool is not a candidate and is omitted.

The hard requirement is fail-open: **every** error path — no registry,
invalid registry, an unreadable note store, anything unexpected — exits 0,
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
otherwise `sys.executable -m tmt`. That path is recorded as invoked and is
deliberately not resolved through symlinks, so a `pipx` install records the
stable `~/.local/bin/tmt` rather than the versioned virtualenv path behind
it, and the hook keeps working when the virtualenv is rebuilt. The
consequence is that a hook installed from a checkout records that
checkout's interpreter: reinstall after changing how tmt is installed, and
`tmt integration plan` reports `update` when the recorded command no longer
matches. `tmt integration print hook claude` prints the fragment
(`{"hooks": {"SessionStart": [<entry>]}}`) for externally managed
configuration and changes nothing.

The merge is surgical and non-destructive: every unrelated setting and every
other hook group (aiq's `UserPromptSubmit` group included) is preserved
byte-for-byte apart from necessary JSON re-serialization (key order is
preserved); missing parent objects/arrays are created and recorded.

Installing over an equivalent but unowned group updates it in place instead
of appending a duplicate beside it: a `SessionStart` group with this matcher
and exactly one `command` hook that runs `tmt context` — under any absolute
`tmt` path or `<python> -m tmt` form — is superseded by the desired entry.
That makes a reinstall after moving tmt (a new pipx path, say) converge on
one hook rather than two.

The settings file is written the same way the registry is: staged, `fsync`ed,
renamed. tmt creates it mode 0600; an existing file keeps its own mode, and a
`settings.json` that is a symlink is followed so the link survives the write
(a dotfiles-managed settings file stays managed).

## Ownership manifest

`${XDG_STATE_HOME:-~/.local/state}/tmt/integration/claude-user.json`, mode
0600, written atomically:

| Field | Meaning |
|---|---|
| `v` | Manifest version, integer `1`; an unsupported version fails closed (`check-failed` for `install`/`uninstall`, `drifted` for `check`) |
| `integration` / `scope` | `"claude"` / `"user"` |
| `settings` | Absolute managed settings path |
| `entry` | The exact owned `SessionStart` group |
| `created_file` | Whether install created the settings file |
| `created_containers` | Containers install added (`hooks`, `hooks.SessionStart`) |

## Lifecycle and drift semantics

Ownership is decided by the manifest, never inferred from settings content.
The owned entry is located by exact (canonical-JSON) equality with the
manifest record. The manifest's recorded `settings` path is authoritative:
it names the file that actually holds the owned entry, so it wins over the
path this environment would derive, and every command reports it.

| Operation | Behavior |
|---|---|
| `plan` | Read-only preview: `install`, `adopt` (entry present, manifest missing), `ok`, `update` (owned entry intact but the desired command changed, e.g. tmt moved), or `drift` (owned entry edited, or the recorded settings path is not the one this environment resolves to). Both drift causes report `status: "drift"`; the boolean `mismatch` distinguishes them — `true` for a recorded-path mismatch, `false` for an edited entry |
| `install` | Idempotent: already installed is success with `changed: false`; `update` replaces the still-intact owned entry; an owned entry edited or removed externally, or a recorded-path mismatch, is refused with code `drift` (exit 3) — nothing is written and the manifest is left alone |
| `check` | `ok` (exit 0), `absent` (no manifest, exit 1), `drifted` (exit 1) — the owned entry is missing or edited, the settings file is unreadable, the recorded path is not this environment's, or the manifest itself is unreadable or an unsupported version. Reported on stdout: `check` never returns an error envelope and never mutates anything, including the manifest |
| `uninstall` | Removes the owned entry only when byte-identical to the manifest record, removes empty containers it created (and the settings file itself when it created it and nothing remains), then deletes the manifest. A tampered same-matcher entry, or a recorded-path mismatch, is refused with `drift` and the manifest survives; an entry already gone just deletes the manifest. Safe to repeat |

A recorded-path mismatch is the `$TMT_CLAUDE_SETTINGS` case: the hook lives
in the recorded file, so tmt refuses to act on the other one rather than
install a second copy or orphan the first. Point the variable back at the
recorded file (or unset it), uninstall there, then install at the new
location.

Because `check` and a refused `install` never delete a manifest they cannot
verify, a drifted state is always recoverable by hand.

Only the `--user` scope exists; it is the default and passing `--user` is
optional.

## Other hosts

The payload is host-neutral plain text, so any host with a session-start hook
can run `tmt context`. Only Claude Code gets a managed lifecycle, because a
lifecycle needs a known settings file that tmt can edit and revert safely.

`tmt integration print hook generic` prints that command as a commented shell
snippet — the last line is `tmt context`, everything above it is comment — for
pasting into whatever the host reads. There is no manifest, no ownership, and
nothing to uninstall, so `plan`, `install`, `check`, and `uninstall` reject
`generic` with `usage` (exit 2). Running the command outside a tmt-enabled
repository prints nothing and exits 0, so it is safe to wire unconditionally.

# tmt — Tool Making Tool

tmt is a registry and scaffolder for repo-local tools: small executables under
`tools/`, indexed by one committed `tmt.json` at the repository root. It exists
so an AI agent (or human) encodes repeatable reasoning once as a tool instead
of re-deriving it every session. tmt is required to make tools, never to run
them: sessions read `tmt.json` and execute `tools/<id>` directly.

> **Alpha:** Distribution and human-interface details may change before 1.0.
> Machine contracts carry their own explicit versions.

| tmt does | tmt does not |
|---|---|
| Keep one committed registry per repo | Run tools — `tools/<id>` executes directly |
| Scaffold born-check-passing Python/sh tools | Depend on anything outside the stdlib |
| Gate drafts and stable tools with `tmt check` | Keep tool state outside the repository |
| Move tools between repos with provenance | Auto-promote or auto-update vendored copies |
| Count re-derivation candidates in untracked local state | Require aiq, or read its journal storage directly |
| Refuse to write outside the repository root | Follow a symlink that leaves the repo |

## Install

tmt supports Python 3.11+ on Linux and macOS with zero runtime dependencies.
It installs from this repository — there is no PyPI release — as the
distribution `tmt-toolmaker`, exposing the `tmt` console entry point. (The
`tmt` name on PyPI belongs to an unrelated project; the distribution name
would avoid that collision if tmt is ever published.)

| Method | Command |
|---|---|
| `pipx` | `pipx install 'tmt-toolmaker @ git+https://github.com/spincyc/tmt.git@main'` |
| `pipx`, a released tag | `pipx install 'tmt-toolmaker @ git+https://github.com/spincyc/tmt.git@v0.1.0a6'` |
| `pipx`, local checkout | `pipx install /path/to/tmt` |
| No install | `PYTHONPATH=/path/to/tmt/src python3 -m tmt --version` |

The `main` ref is the development channel and a tag is the stable one; either
requires Git and network access at install time. A local-checkout install is a
frozen snapshot of the working tree — useful for development, but it does not
track later commits.

tmt never updates itself: an installed copy stays at whatever it was installed
from while the repository advances. Refresh it explicitly:

```sh
pipx install --force \
  'tmt-toolmaker @ git+https://github.com/spincyc/tmt.git@main'
tmt --version
```

## Quickstart

Run this inside the repository whose tools you want to index. `tmt init`
creates an empty `tmt.json` in the current directory and prints the two-line
stanza to paste into the repo's `AGENTS.md`.

```sh
repo=$(mktemp -d)
cd "$repo"

tmt init

tmt new changed-files \
  --purpose "List files changed vs merge-base, one per line" \
  --usage "tools/changed-files [--json] [BASE]"

tools/changed-files --help
tmt list
tmt check

cat >> tools/changed-files.test <<'EOF'
"$tool" --json | grep -q '"v":1'
EOF
tmt stage changed-files stable

tmt check
```

`tmt new` scaffolds a Python tool by default (`--lang sh` for wrapper-thin
pipelines) that already passes every draft gate — shebang, `--help`, and a
`--json` stub emitting one compact key-sorted object with `"v": 1` — plus a
born-passing `tools/<id>.test` smoke test that asserts only `--help` exits 0
(the sole universal guarantee) and carries a commented skeleton for real
assertions. Paste the derived logic into the scaffold's `run()` body, write
real test assertions, and commit. `tmt stage <id> stable` promotes the tool
after running the full stable gate battery — it refuses while the test is
still the unmodified scaffold. Put `tmt check` in the repo's existing verify
target so a stale registry is a build failure.

## Find the right operation

| Need | Command |
|---|---|
| Create the registry | `tmt init` |
| Scaffold a tool, its smoke test, and its draft entry | `tmt new <id>` |
| Survey the registry | `tmt list [--stage draft\|stable]` |
| Inspect one tool: entry, `--help`, long doc | `tmt show <id>` |
| Run every gate, collect every failure | `tmt check` |
| Gate one tool only, running nothing else | `tmt check <id>` |
| Promote or demote through the gates | `tmt stage <id> <draft\|stable>` |
| Change one entry field, validated before saving | `tmt set <id> <field> <value>` |
| Rename a tool, its files, and every dependent | `tmt rename <id> <new-id>` |
| Delete a tool and its files | `tmt rm <id> [--keep-files]` |
| Record "re-derived this again", see the running count | `tmt note <slug> [--note TEXT]` |
| Count recorded candidates, or forget one | `tmt candidates [--dismiss <slug>]` |
| Copy a tool in, stamped with provenance | `tmt vendor <source-repo> <id>` |
| Lint and copy a tool out | `tmt adopt <id> --to <dest-repo>` |
| Report or install the AGENTS.md habit fragment | `tmt agents [--write]` |
| Print the canonical fragment or a hook fragment | `tmt integration print agents\|hook claude\|hook generic` |
| Manage the Claude Code session hook | `tmt integration plan\|install\|check\|uninstall claude` |
| Emit session context (the hook payload) | `tmt context` |
| See command flags | `tmt COMMAND --help` |

Every command except `tmt context` (plain text by design) accepts `--json`
and speaks the [CLI JSON protocol v1](docs/contracts/cli-v1.md). No command
requires anything beyond tmt: `tmt note` records into untracked machine-local
state and, when the optional sibling tool aiq is on `PATH`, mirrors the note
to it best-effort — a mirroring failure never fails the note, and
`tmt candidates` counts the local store either way.

`tmt stage` is the only way to move a tool between stages, and `tmt set`,
`tmt rename`, and `tmt rm` maintain everything else, so `tmt.json` never needs
hand-editing.

## Running an untrusted repository's tools

Two commands execute the repository's own code:

| Command | What it runs |
|---|---|
| `tmt check` | `tools/<id> --help` for every registered tool, and `tools/<id>.test` for every stable one |
| `tmt check <id>` | the same gates, for that one tool only |
| `tmt show <id>` | `tools/<id> --help` for that one tool |

In a repository someone else wrote, those are that repository's programs
running as the invoking user. Read the tools before checking a fresh clone.
Timeouts (5s for `--help`, 60s for a test) and process-session isolation bound
a hang, not the code's authority.

The session hook is deliberately different. `tmt context` reads `tmt.json` and
the local note store and executes nothing at all; the repo-supplied strings it
prints are stripped of control characters, collapsed to one line, capped at 120
characters, and labelled as repo-supplied data rather than tmt instruction —
a cloned repo's `purpose` text lands in an agent's session context, so it is
presented as data about that repo, not directions from tmt.

Writes are contained: every path tmt writes is resolved first, and one landing
outside the repository root is refused (`containment`, exit 3) instead of
followed — a `tools` symlink, an `AGENTS.md` symlink, or a vendor source
pointing out of its repo. Registry and `AGENTS.md` writes are staged and
renamed, so an interrupted save cannot truncate a committed file.

## Session integration

The note habit needs ambient presence: guidance loads at session start, but
the noteworthy moment is mid-session. Three layers keep it present, each
optional and reversible:

| Layer | Surface | Command |
|---|---|---|
| Fragment | Canonical 4-line AGENTS.md text, versioned | `tmt integration print agents` |
| Marker block | Owned block in the repo's AGENTS.md, gated by `tmt check` | `tmt agents --write` (or `tmt init --agents`) |
| Session hook | Claude Code `SessionStart` hook running `tmt context` | `tmt integration install claude` |
| Any other host | The same command as a shell snippet to paste into that host's session-start hook | `tmt integration print hook generic` |

`tmt context` prints the repo's tool list and the noted candidates not yet
built at session start, and is fail-open by contract — it never breaks a
session. The hook lifecycle is manifest-owned and drift-safe: install is
idempotent, uninstall removes only the unmodified owned entry, and every
unrelated setting is preserved. See the
[integration contract](docs/contracts/integration-v1.md).

Only Claude Code has a managed lifecycle, because only a known settings file
can be edited and reverted safely. The payload itself is host-neutral plain
text, so any host with a session-start hook can run `tmt context` — that is
what the `generic` fragment prints, with no manifest and nothing to
uninstall.

## Documentation

| Topic | Use it for |
|---|---|
| [Design record](DESIGN.md) | Settled decisions and their rationale |
| [Concepts](docs/concepts.md) | Lifecycle stages, composition, the note store and aiq seams, extraction tiers |
| [CLI JSON v1](docs/contracts/cli-v1.md) | Command surface and versioned JSON envelopes |
| [Registry v1](docs/contracts/registry-v1.md) | `tmt.json` format, fields, and semantic rules |
| [Errors](docs/contracts/errors.md) | Stable codes and exit categories |
| [Vendoring v1](docs/contracts/vendoring-v1.md) | vendor/adopt semantics, origin stamps, drift |
| [Integration v1](docs/contracts/integration-v1.md) | AGENTS.md fragment, marker block, session hook lifecycle |

The normative registry schema is
[`schemas/tmt-v1.schema.json`](schemas/tmt-v1.schema.json).

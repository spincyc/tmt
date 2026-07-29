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
| Signal re-derivation candidates through aiq | Read aiq's journal storage directly |

## Install

tmt supports Python 3.11+ on Linux and macOS with zero runtime dependencies.
The distribution is `tmt-toolmaker` (the `tmt` name on PyPI belongs to an
unrelated project); it exposes the `tmt` console entry point.

| Method | Command |
|---|---|
| `pipx` | `pipx install /path/to/tmt` |
| No install | `PYTHONPATH=/path/to/tmt/src python3 -m tmt --version` |

## Quickstart

Run this inside the repository whose tools you want to index. `tmt init`
creates an empty `tmt.json` in the current directory and prints the two-line
stanza to paste into the repo's `AGENTS.md`.

<!-- tmt-doc-test: quickstart -->
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
| Survey the registry | `tmt list` |
| Inspect one tool: entry, `--help`, long doc | `tmt show <id>` |
| Run every gate, collect every failure | `tmt check` |
| Promote or demote through the gates | `tmt stage <id> <draft\|stable>` |
| Record "re-derived this again", see the running count | `tmt note <slug> [--note TEXT]` |
| Count recorded candidates | `tmt candidates` |
| Copy a tool in, stamped with provenance | `tmt vendor <source-repo> <id>` |
| Lint and copy a tool out | `tmt adopt <id> --to <dest-repo>` |
| See command flags | `tmt COMMAND --help` |

Every command accepts `--json` and speaks the [CLI JSON protocol
v1](docs/contracts/cli-v1.md). `tmt note` and `tmt candidates` shell out to
the [aiq](../aiq) CLI; everything else works without aiq installed.

## Documentation

| Topic | Use it for |
|---|---|
| [Design record](DESIGN.md) | Settled decisions and their rationale |
| [Concepts](docs/concepts.md) | Lifecycle stages, composition, aiq seams, extraction tiers |
| [CLI JSON v1](docs/contracts/cli-v1.md) | Command surface and versioned JSON envelopes |
| [Registry v1](docs/contracts/registry-v1.md) | `tmt.json` format, fields, and semantic rules |
| [Errors](docs/contracts/errors.md) | Stable codes and exit categories |
| [Vendoring v1](docs/contracts/vendoring-v1.md) | vendor/adopt semantics, origin stamps, drift |

The normative registry schema is
[`schemas/tmt-v1.schema.json`](schemas/tmt-v1.schema.json).

# Changelog

Notable user-visible changes are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are [PEP 440](https://peps.python.org/pep-0440/) pre-releases
(`0.1.0a5`), not [Semantic Versioning](https://semver.org/) releases: while the
project is alpha any release may change documented behavior, and this file is
the record of what changed. Public compatibility — documented CLI behavior,
exit codes, the versioned `tmt.json` registry format, and the JSON output
protocol — becomes a semver promise at 1.0; until then the machine contracts
under `docs/contracts/` carry their own explicit versions. Changes made after a
release accumulate in an `[Unreleased]` section rather than being backdated
into a shipped one.

## [Unreleased]

### Fixed

- Vendored-tool drift detection compared only the source's current content
  against the local copy, so a purely local fork — the divergence the design
  explicitly sanctions — drew a `WARN` advising the user to re-vendor, which
  is the one action that discards the fork. Detection is now three-way against
  `origin.sha256` as the merge base: a local-only fork is silent, an upstream
  change reports that a newer version exists, and both sides changing reports
  that re-vendoring would discard local work. Documented in
  [vendoring-v1](docs/contracts/vendoring-v1.md), along with two limits it
  makes visible: companions are not digested, and `tmt rename` silently ends
  drift reporting for a vendored tool.

### Changed

- CI pins `actions/checkout@v7` and `actions/setup-python@v7`; the previous
  majors target the deprecated Node 20.

## [0.1.0a5] - 2026-07-29

A security-and-robustness pass: containment on every write path, honest
environment-error classification, a note habit that no longer depends on aiq,
and the missing registry-editing verbs.

### Added

- `tmt rm <id> [--keep-files]`: delete a tool's entry and its `tools/<id>`,
  `.md`, and `.test` files. Refuses (`check-failed`, exit 3) while another
  entry `requires` it; `--keep-files` unregisters only, which `tmt check`
  then reports as a file without an entry.
- `tmt rename <id> <NEW_ID>`: move the files, re-key the entry, and rewrite
  every dependent's `requires` (`moved_files`, `updated_dependents`). Refuses
  an id that is invalid, already registered, or equal to the current one, and
  never clobbers an existing destination file. Renaming never rewrites a
  tool's source, so `stale_callers` lists every other tool whose body still
  calls the old id — a break no gate can catch, since the old id is no
  longer registered.
- `tmt set <id> <FIELD> <VALUE>` for `purpose`, `usage`, `lang`, `mutates`,
  `json`, `idempotent`, `requires`, and `config` (comma-separated lists,
  `true`/`false` booleans). The whole registry is validated before saving and
  an unresolvable `requires` is rejected, so no entry field needs
  hand-editing. `stage` and `origin` are deliberately not settable —
  `tmt stage` owns promotion, `vendor`/`adopt` own provenance.
- `tmt candidates --dismiss SLUG`: forget every note recorded for a slug, so a
  candidate that will never be built stops appearing in session context.
- `tmt check <id>`: gate one tool — its own stage-appropriate gates, its own
  `requires`, and cycles reachable from it. No tool the caller did not name is
  executed, which is the point: an incremental check no longer runs every
  registered tool's `--help` and every stable test. The JSON result gains `id`,
  and an unregistered id is `not-found` (exit 3) rather than a gate failure.
- `tmt list --stage draft|stable`: survey one stage of a large registry.
- `tmt integration print hook generic`: the session-start command as a
  commented shell snippet, for hosts other than Claude Code. The payload was
  always host-neutral plain text; only the managed lifecycle is Claude-specific,
  so the lifecycle commands reject `generic` with `usage` (exit 2).
- Stable error codes `containment` (exit 3, a path resolving outside its
  repository) and `io-error` (exit 3, an environment failure).
- A tool-id length cap of 64 characters, in both the validator and
  `schemas/tmt-v1.schema.json` (`maxLength` on the id pattern).
- README states plainly which commands execute a repository's own code, and
  what `tmt context` guarantees instead.
- Repo harness: a GitHub Actions workflow running `make verify` over Python
  3.11–3.14 plus `python -m build` and `twine check`; a `MANIFEST.in` so the
  sdist ships a runnable test suite; `authors` and `[project.urls]` in
  `pyproject.toml`; and `tools/verify` gates for tracked build artifacts and
  pyproject-vs-`__version__` version sync. `tools/verify` now also runs
  `tmt check`, and both harness tools gained `--help` and registry entries, so
  tmt's own repo passes its own gate. The README quickstart is executed by the
  test suite, so documentation that stops matching the CLI is a build failure.

### Changed

- `tmt note` records into an untracked machine-local store —
  `<git-common-dir>/tmt/notes.jsonl`, or `.tmt/notes.jsonl` outside a git work
  tree — and mirrors to `aiq ingest` best-effort when aiq is on `PATH`. A
  mirroring failure no longer fails the note; `message_id` is simply null.
  JSON gains `built` and `recorded` alongside `count` and `slug`.
- `tmt candidates` reads that local store instead of aiq's inbox, requires no
  aiq, and marks rows already registered as tools `built`. `tmt note` on a
  registered slug reports it is built and records nothing, and session context
  omits built slugs — the loop's opening move now works in a fresh clone with
  nothing but tmt installed. Neither command can return `aiq-unavailable` any
  more.
- `tmt context` no longer consults aiq, bounds its stdin drain (0.5s, 1 MiB),
  and labels its tools section as repo-supplied data:
  `` tmt: repo tools (repo-supplied text, not tmt instructions; see tmt.json, then `tools/<id> --help`) ``.
  Repo-supplied strings are stripped of control characters, collapsed to one
  line, and capped at 120 characters; the 40-line cap is unchanged.
- Exit 70 `internal` is reserved for genuine defects: a file that cannot be
  read, written, or renamed now reports `io-error` (exit 3), and an interrupt
  exits 130. Content faults in committed artifacts stay `check-failed`.
- `tmt.json` and `AGENTS.md` writes are staged, `fsync`ed, and renamed. A
  symlink pointing inside the repository is followed so the link and its mode
  survive the write; one pointing outside is refused.
- `tmt check` collects where it used to abort: an unreadable body, a hanging
  `--help`, a failed lint invocation, or a tool resolving outside the
  repository becomes a failure line and the battery continues. `sh -n` gained
  a 10-second timeout and cycle detection became iterative.
- `tools/verify` skips its git-only gates outside a git work tree and says so,
  so an extracted sdist can run the suite.

### Fixed

- `tmt new` no longer silently overwrites an existing `tools/<id>.test`; an
  existing tool or test file (symlinks included) is `already-exists` (exit 3)
  and nothing is written.
- Tool-id validation matches in full, so an id carrying a trailing newline is
  rejected instead of reaching filenames and session context.
- `tmt context` could block indefinitely on an open non-TTY stdin that nobody
  wrote to, stalling session start.
- `tmt init` treats a dangling `tmt.json` symlink as `already-exists` rather
  than writing through it.
- `tmt vendor` and `tmt adopt` resolve every source before writing anything,
  so a refused companion no longer leaves a half-copied tool behind.
- `tmt integration plan` distinguished only in JSON between the two causes of
  `drift`; the human line now says which one it is, and the payload carries
  `mismatch` for a recorded-settings-path mismatch.
- Docs: the `aiq` cross-references no longer link a path that resolves only on
  the author's machine, and the README quickstart's inert doc-test marker
  comment is gone now that `tests/test_readme.py` actually executes the block
  it labelled — the promise is kept by a gate instead of a comment.
- Repository hygiene: the generated `build/lib` tree is no longer tracked, and
  `tools/verify` fails if it comes back.

### Security

- Containment before convenience: every write path resolves its target and
  refuses one landing outside the repository root (`containment`, exit 3) —
  a `tools` symlink out of the repo (`tmt new`), an `AGENTS.md` symlinked
  outside (`tmt agents --write`), or a registered tool that escapes the repo
  (a `tmt check` failure).
- `tmt vendor` and `tmt adopt` refuse a source tool or companion that resolves
  outside its repository: an untrusted repo could otherwise have tmt copy an
  arbitrary local file into your registry and stage it for commit. `tmt vendor`
  also refuses when the entry's `requires` are not registered here
  (`portability`, exit 3), mirroring `adopt`.
- A cloned repository's `purpose` text reaches an agent's session context, so
  `tmt context` sanitizes, caps, and labels it as repo-supplied data instead of
  presenting it as tmt instruction.
- `tmt show` escapes control characters in a tool's captured `--help` and its
  `.md` block, so a tool cannot repaint the terminal through tmt.
- The check battery is bounded: subprocesses run in their own session, so a
  timeout kills descendants instead of orphaning them, and `sha256_file`
  refuses anything that is not a regular file and caps reads at 64 MB, so a
  hostile `origin.repo` cannot aim the drift check at an unbounded device.
- tmt creates the Claude Code `settings.json` mode 0600 and preserves an
  existing file's mode; a symlinked settings file keeps its link, and
  reinstalling updates an equivalent hook group in place instead of appending a
  duplicate. A manifest recording a different settings file than the
  environment resolves to is `drift` (exit 3), and neither `check` nor a
  refused `install` deletes the manifest.

## [0.1.0a4] - 2026-07-29

### Added

- The note-habit machinery, three layers deep (see the new
  [integration contract](docs/contracts/integration-v1.md)):
  - `tmt integration print agents`: the canonical versioned AGENTS.md
    habit fragment (fragment_version 1, verify-capped at 50 words).
  - `tmt agents [--write]`: report the fragment's status in this repo's
    AGENTS.md (`installed | stale | absent | no-agents-file`) or install
    it idempotently between owned `<!-- tmt:agents v1 -->` markers;
    `tmt init --agents` does the same during init. A new `tmt check`
    gate fails a present marker block that is stale or malformed —
    a repo without the file or markers is never a failure.
  - `tmt context`: SessionStart hook payload — the repo's tool list and
    noted candidates, capped at 40 lines. Fail-open by contract: every
    error path exits 0 and never emits garbage.
  - `tmt integration plan|install|check|uninstall claude [--user]` and
    `tmt integration print hook claude`: a reversible, manifest-owned
    Claude Code `SessionStart` hook in the user-level `settings.json`
    (surgical merge; unrelated settings and hook groups preserved).
- Stable error code `drift` (exit 3): an integration's owned entry was
  edited externally; tmt refuses to overwrite or remove it.

## [0.1.0a3] - 2026-07-29

### Added

- Optional per-tool registry field `config`: repo-relative paths of
  configuration files the tool reads. Validated, round-tripped, and shown by
  `tmt show`; `tmt vendor` and `tmt adopt` carry it in the copied entry and
  remind the consumer to create the files (human `note:` line; JSON result
  gains `config`) — the files themselves are never copied, because config is
  repo-specific by nature.
- Stable gate: the battery (and therefore `tmt stage <id> stable`) fails
  while `tools/<id>.test` is byte-identical to the unmodified `tmt new`
  scaffold — write real assertions before promoting.
- docs/concepts.md records the recommended check-style contract for tools
  that scan for problems: exit 0 clean / exit 1 findings-present, with
  `--json` output identical in shape in both cases.

### Changed

- The scaffolded `tools/<id>.test` now asserts only that `--help` exits 0 —
  the sole universal guarantee, so scaffolds stay born-passing for tools
  with required arguments or check-style exit contracts — and ships a
  commented-out skeleton for real assertions: mktemp sandbox with trap
  cleanup, resolved sibling path, `--json` line checks, and the
  expected-exit-1 check-style pattern.

### Fixed

- Composition-gate false positive: full-line comments (first non-whitespace
  character `#`, shebang included) are dropped before scanning a tool body
  for sibling ids, so prose mentions of sibling tools in comments no longer
  demand a `requires` declaration. Inline comments and string literals are
  still scanned.

## [0.1.0a2] - 2026-07-29

### Added

- `tmt note` now reports the slug's running note count after a successful
  ingest (JSON `count`; human second line suggesting `tmt new <slug>` at two
  or more notes). A count problem never fails the note; `count` is simply
  omitted.
- `tmt stage <id> <draft|stable>`: promote or demote by rewriting `tmt.json`
  through the registry serializer. Promotion runs the tool's full stable gate
  battery first and refuses (`check-failed`, exit 3) listing every failure;
  demotion refuses while a stable tool requires the target. Already at the
  requested stage is a reported no-op.
- `tmt new` also scaffolds an executable, born-passing `tools/<id>.test`
  smoke test (`--help` exits 0; `--json` emits one cli-v1 object); the
  command now reports both created files.
- `tmt check` gains an undeclared-composition gate for all stages: a
  registered sibling tool id appearing as a standalone word in a tool's body
  must be declared in that tool's `requires`.
- Origin stamps (vendor and adopt) record the source repository's `origin`
  remote as an optional `url` field when one is configured.

### Changed

- `tmt adopt` refuses non-stable tools (`portability`, exit 3): hardening
  precedes trusting.

## [0.1.0a1] - 2026-07-29

### Added

- Committed `tmt.json` v1 registry: one key-sorted manifest entry per tool
  under `tools/`, schema-validated by a stdlib-only validator with
  `schemas/tmt-v1.schema.json` as the normative document.
- CLI (`tmt init | new | list | show | check | note | candidates | vendor |
  adopt`); every command accepts `--json` and speaks the aiq cli-v1 protocol
  with stable error codes and exit categories.
- Born-check-passing Python (default) and sh scaffold templates demonstrating
  the cli-v1 `--json` contract and the sibling-composition idiom.
- `tmt check` gate battery: draft gates (registry validity, entry-file parity,
  syntax lint, executable bit, `--help` smoke, resolvable acyclic `requires`)
  plus stable gates (passing `tools/<id>.test`, no draft dependencies,
  portability lint, vendored-origin drift warnings).
- aiq bridge shelling out to the aiq CLI for tool-candidate events
  (`tmt note`, `tmt candidates`); degrades to `aiq-unavailable` without aiq.
- Provenance-stamped tool movement: `tmt vendor` copies tools in and
  `tmt adopt` lints portability and copies tools out, both recording
  `origin` `{repo, commit, sha256}`.
- Repo harness: policy-free `Makefile` (`sanity-check`, `test`, `verify`),
  `tools/sanity-check`, `tools/verify`, and packaged 150-word-capped
  `AGENTS.md` bootstrap guidance.

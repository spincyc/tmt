# Changelog

Notable user-visible changes are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are [PEP 440](https://peps.python.org/pep-0440/) pre-releases
(`0.1.0a6`), not [Semantic Versioning](https://semver.org/) releases: while the
project is alpha any release may change documented behavior, and this file is
the record of what changed. Public compatibility — documented CLI behavior,
exit codes, the versioned `tmt.json` registry format, and the JSON output
protocol — becomes a semver promise at 1.0; until then the machine contracts
under `docs/contracts/` carry their own explicit versions. Changes made after a
release accumulate in an `[Unreleased]` section rather than being backdated
into a shipped one.

## [Unreleased]

### Changed

- Two open design questions are closed as settled decisions, with their
  rationale and revisit conditions in [DESIGN.md](DESIGN.md): `stage` gains no
  `deprecated` value, and a scaffolded tool has no upgrade path to a newer
  template. Both are documentation-only — the point of each is that nothing
  gets built. `docs/concepts.md` now states that a scaffold is a starting
  point rather than a live dependency.

- tmt's own `tools/sanity-check` and `tools/verify` are `stable`, with real
  tests. They had sat at `draft` with no test — the state tmt exists to
  prevent elsewhere — so the dogfood claim was thinner than it read.
  `verify.test` deliberately does not run the battery, since `tmt check` runs
  the test and `verify` runs `tmt check`; it pins the `--help` short-circuit
  that makes that recursion impossible, and that a raising check still fails
  the run.
- tmt is distributed from this repository only, matching aiq: `pipx install
  'tmt-toolmaker @ git+…@main'`, or a tag for a stable pin. The PyPI publish
  workflow is removed — it worked up to the upload and failed only for want of
  a trusted publisher, and a second channel is a second thing to keep honest.
  The tag-versus-version guard moved into CI, because a tag is now the only
  stable pin: a tag whose commit declares a different version would install as
  that other version with no warning.

### Fixed

- **Concurrent tmt processes silently lost one another's work.** Every
  registry command is a read-modify-write, and only the write was atomic, so
  two sessions in one repository could each load `tmt.json`, mutate it, and
  clobber the other. Reproduced: six concurrent `tmt new` calls kept two of
  six entries and left four scaffolded files with no entry, failing
  `tmt check`. Mutations now hold one per-repository `flock` across the whole
  read-modify-write (`registry.updating`), in the untracked state directory so
  no work tree gains a file to commit. The lock is `flock` rather than a file
  whose existence means locked, because the kernel releases it when the holder
  dies — the alternative would wedge every later run after one `kill -9`.
  Waiting is bounded (5s, then `io-error`), never indefinite, and the
  read-only paths — `list`, `show`, `check`, `context`, `candidates` — take no
  lock at all, so the fail-open session hook still cannot block. The note
  store's append and dismiss are serialized the same way.
- Renaming a vendored tool silently ended its drift reporting: the source path
  was derived from the current id, which never existed upstream, and the
  resulting read error was indistinguishable from "no drift". The origin stamp
  now records `origin.id`, the source-side id, and drift resolves through it.
  Additive and optional per the registry contract's versioning rule; a stamp
  written before it falls back to the local id.

### Changed

- The undeclared-composition gate matches a sibling id only in a **path
  position** — preceded by `/`, at most a quote and whitespace between — where
  the mandated adjacency idiom puts it. Matching the bare word made a tool
  named after an ordinary word unusable: the scaffold's own text contains
  `json`, so `tmt new json` failed every other tool in the repository and no
  `requires` declaration could fix a dependency that did not exist. Path
  strings, which are why string literals are scanned at all, still match. The
  same rule now governs `tmt rename`'s stale-caller warning.

### Added

- `tmt check` warns when a tool's `lang` has no syntax gate, naming the tool,
  the language, and what was skipped. Other languages stay permitted — the
  schema allows them deliberately — but a silently unlinted body is no longer
  reported as a clean `ok`. Promotion is unaffected: `tmt stage` still runs
  exactly the failure battery, so an escalated language stays promotable.
- Test coverage for the paths a review found unexercised: the Claude Code
  hook's malformed settings and manifest inputs (with the user's file asserted
  byte-identical on every refusal), its console-script command branch, the
  check battery's two timeout paths and descendant kill, `sha256_file`'s
  refusals, a non-executable stable test, non-ASCII and astral-plane output,
  and that a hostile `purpose` cannot forge session-context structure. Every
  new test was mutation-verified against the guard it covers.

### Changed

- `tests/_support.py` points `HOME` and `XDG_STATE_HOME` at a session sandbox,
  so no test can reach the developer's own state even if a future code path
  resolves them.
- `sessioncontext`'s per-value truncation constant is named `MAX_VALUE_CHARS`,
  and the contracts say per *value* rather than per line: the composed line
  also carries tmt's own text and can exceed it. No public path reaches the
  cap — the validator bounds a purpose at 80 characters and an id at 64 — so it
  stands as a backstop, not a live limit.

### Removed

- `notestore.slug_count`, which had no caller.

## [0.1.0a6] - 2026-07-29

The first release published to PyPI, and a second security pass: containment
now covers each operation's companions and destinations, not only its primary
path, and the two reviews behind these fixes were run by agents that had not
written the code.

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
  drift reporting for a vendored tool (fixed after this release by
  `origin.id`).
- Containment covered a primary path but not its companion or its
  destination, in three places an independent review reproduced:
  `tmt vendor`/`tmt adopt` wrote through a symlinked *destination* (and
  `copymode` made the outside file executable); `tmt check` executed a
  `tools/<id>.test` symlinked out of the repository and still reported `ok`;
  and `tmt show` executed the tool and read its `.md` with no gate at all,
  leaking a doc from outside the clone. Every destination and companion is
  now resolved before use, copies are created `O_NOFOLLOW` with the mode set
  through the descriptor, and a refusal in `tmt check` is a collected failure
  line rather than an exception.
- `tmt agents --write` could delete a user's own text and never converge.
  `_splice` split lines with `str.splitlines`, which also breaks on `\x0b`,
  `\x0c`, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029, while the locator split
  on `\n` alone — so a form-feed page break made the two disagree about where
  the owned block was. The module now has one notion of a line.
- `tmt rm` and `tmt rename` checked preconditions inside the mutation loop, so
  a refusal on the second file landed after the first had already moved,
  leaving the registry pointing at a file that no longer existed. Both now
  validate the whole plan first, and a failed move sequence unwinds. Relatedly,
  refusing an out-of-repo companion *symlink* was a category error — `unlink`
  and `rename` never follow one — and made the tool unremovable; containment
  for those operations belongs on the `tools` directory.
- `tmt set requires` could write a cycle, or put a draft under a stable tool —
  exactly what `tmt check` forbids — so a command that exited 0 left the
  repository red. The graph rules now gate the edit.
- Two inputs still escaped the check battery to exit 70: a deeply nested
  `tmt.json` (`json.loads` raises `RecursionError`, which is not a
  `JSONDecodeError`) and a tool whose `--help` writes unboundedly, which
  `communicate` bounded in time but not in bytes. Both are collected failures
  now, the second against a 1 MiB per-stream cap that reports the truncation
  rather than silently clipping.
- `tmt show` reported a non-UTF-8 `tools/<id>.md` as an internal defect; it is
  `check-failed` (exit 3). Escapes above U+FFFF were emitted as malformed
  5-hex `\uXXXXX` sequences and now use `\UXXXXXXXX`.
- The local note store could be committed: a registry in a subdirectory of a
  repository wrote `.tmt/notes.jsonl` into the work tree. The fallback store
  now carries a `.gitignore`. Resolution deliberately does *not* walk upward
  the way git does — a stray ancestor `.git` (a dotfiles repository at `$HOME`,
  or a `git init` left in `/tmp`) would otherwise capture an unrelated
  repository's notes.
- `paths.write_atomic` staged through a pid-derived filename, so a leftover
  from a killed process wedged every later write by that pid; it now uses
  `mkstemp`. It also fsyncs the parent directory after the rename, and both
  writers set the mode through the open descriptor rather than by path after
  closing it.
- The `undeclared_composition` gate recompiled a regex per (tool, sibling)
  pair, thrashing the pattern cache: 800 tools took 14.7s, now 0.14s.

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

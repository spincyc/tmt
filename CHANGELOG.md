# Changelog

Notable user-visible changes are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/). Public
compatibility covers documented CLI behavior, exit codes, the versioned
`tmt.json` registry format, and the JSON output protocol.

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

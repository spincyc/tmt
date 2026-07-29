# Changelog

Notable user-visible changes are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/). Public
compatibility covers documented CLI behavior, exit codes, the versioned
`tmt.json` registry format, and the JSON output protocol.

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

# tmt — Tool Making Tool

Design record, 2026-07-29. Decisions below were made with the owner; treat them
as settled unless the owner supersedes them here.

## Purpose

tmt lets AI agents (and humans) turn repeatable, re-derived reasoning into
small, well-documented, composable repo-local tools, so future sessions run a
tool instead of re-deriving knowledge. It operationalizes the existing
guidance directive (aiq AGENTS.md, ai-guidance/00-core.md): "when reasoning
becomes repeatable, encode it in the smallest deterministic tool."

## Relationship to aiq (decided: sibling with seams)

tmt is its own system. aiq owns work state (messages, tasks, queue, journal);
tmt owns durable executable knowledge (making, indexing, composing, promoting
tools). Neither requires the other. Seams:

| Seam | Mechanism |
|---|---|
| Candidate signal | "Re-derived X again" events go to `aiq ingest --event-json -` (v1 envelope). tmt owns no event storage; `tmt candidates` reads aiq's journal. |
| Tool-building as work | Crossing the candidate threshold files an aiq task; building a tool is queued, journaled work. |
| Guidance | Cross-pointing only; each policy owned by one document. aiq's "smallest deterministic tool" line points at tmt. |
| Contracts | tmt adopts aiq cli-v1 wholesale: `--json` emits one compact key-sorted object with `"v":1`; errors `{"code","error","status":"error","v":1}` on stderr; stable codes + exit categories. One protocol across aiq, tmt, and every generated tool. |
| State placement | Untracked runtime state (if any) under `$(git rev-parse --git-common-dir)/tmt/`, aiq resolve_scope precedent. |

## The registry (decided: one committed file, `tmt.json`)

`tmt.json` at repo root is the single canonical artifact: registry config plus
one manifest entry per tool. Tools are pure executables under `tools/` — no
comment-header grammar, no per-tool manifest files. Schema-validated
(`additionalProperties: false`), key-sorted for clean diffs.

```json
{
  "v": 1,
  "tools": {
    "changed-files": {
      "purpose": "List files changed vs merge-base, one per line",
      "usage": "tools/changed-files [--json] [BASE]",
      "stage": "stable",
      "mutates": false,
      "json": true,
      "requires": [],
      "origin": "local"
    }
  }
}
```

- `purpose` hard-capped at 80 chars — it is the per-session discovery cost
  (~15 tokens/tool for one Read of tmt.json).
- `mutates`/`idempotent` reuse aiq's capability-descriptor vocabulary.
- Agents run `tools/<id>` directly: tmt is required to make tools, never to
  run them. `--help` always works; `tools/<id>.md` optional long doc.

## Language policy (decided: Python-first)

Tools default to python3, stdlib-only (`tmt new` scaffolds Python unless
`--lang sh` is given). Rationale: the cli-v1 `--json` contract is trivial in
Python and error-prone in sh; one default language means one lint battery, one
test idiom, one composition model. `sh` is the documented exception for
wrapper-thin pipelines; other languages are permitted only when measured
performance or a required feature forces the escalation, recorded in the
tool's `lang` field.

## Tool lifecycle (decided: escalating ceremony)

Rationale: the dominant failure mode is ceremony friction — if making a tool
costs more than one more re-derivation, agents defect and the registry
starves. Drafts are nearly free; ceremony attaches at `stable`, which is when
composition and extraction start trusting the tool.

| Stage | Cost to enter | `tmt check` enforces |
|---|---|---|
| `draft` | `tmt new <id>` + paste derived logic | entry↔file parity, syntax lint, `--help` smoke, `requires` resolve, no cycles |
| `stable` | add `tools/<id>.test` (exit 0 = pass) | draft checks + test passes + `--json` conforms to cli-v1 + no repo-hardcoded paths |

- `stable` may not `require` a `draft` — hardening pressure flows down the
  dependency graph.
- Drafts may live indefinitely; only penalty is exclusion from stable
  composition.
- `tmt check` is one line in each repo's existing `make verify`, so a stale or
  lying `tmt.json` is a build failure, not a discovery.

## Composition

A tool calls a sibling as `"$(dirname "$0")/<id>"` (spec-mandated form) and
declares it in `requires`. No PATH mutation, no registry lookup at runtime.
Composed tools inherit every hardening their dependencies receive.

## The loop

1. Agent notices re-derivation → emits candidate event via aiq ingest.
2. Second occurrence → `tmt candidates` surfaces it; aiq task created.
3. `tmt new <id> --lang sh|py` scaffolds executable + tmt.json entry, born
   check-passing; agent pastes logic, commits (smallest coherent diff).
4. Next session Reads tmt.json, runs the tool: ~40 tokens vs ~1,500.
5. Edge cases fixed in place (prefer editing over near-duplicates); test
   added; stage flipped to stable. Git history is the audit trail.

## Extraction (decided: tier-2 = new `tmt-lib` repo; vendoring, never linking)

The spec has no pool concept. Tier-2 is an ordinary tmt-enabled repo
(`~/git/tmt-lib`) that happens to contain only tools. Movement is symmetric
copying with provenance:

- `tmt vendor <repo> <id>` — copy executable + tmt.json entry into the
  current repo, stamping `"origin": {"repo", "commit", "sha256"}`.
  `tmt check` warns (never fails) when the source has newer.
- `tmt adopt <id> --to <repo>` — the reverse: agent prepares the copy into
  tmt-lib with a portability lint (no absolute/repo-specific paths;
  `requires` must be promotable together); the human approves by committing.
  Promotion is never automatic.
- Tools about tool-making graduate one step further, into tmt itself, by
  ordinary PR.
- Divergence after vendoring is allowed (per-repo fitness beats shared-dep
  correctness); re-vendoring is a deliberate overwrite.

## tmt's own repo

Mirrors aiq conventions: stdlib-only Python 3.11+, src-layout, zero deps,
console entry `tmt.cli:main`, `make test/verify/ci`, versioned
`docs/contracts/`, JSON Schemas in `schemas/`, ≤150-word byte-verified
AGENTS.md, doc-tested README, Keep-a-Changelog. tmt's repo is itself
tmt-enabled (dogfood). CLI surface (all commands take `--json`):

`init | new | list | show | check | candidates | vendor | adopt`

Guidance wiring: new `ai-guidance/15-tool-making.md` registered in
AI_GUIDANCE.md's ordered list (respect the 250-word entry budget); per-repo
AGENTS.md gains two lines pointing at tmt.json and `tmt new`.

## Open questions

- **Name collision**: `tmt` is taken on PyPI (teemtee's Test Management Tool,
  packaged in Fedora). Fine for a personal CLI; needs a distribution name
  (aiq precedent: `aiq-workqueue`) or a rename if ever published.
- Candidate threshold default (2 events across distinct sessions?) and where
  it is configured (tmt.json config block?).
- tmt.json merge conflicts on concurrent branches: sorted keys + one object
  per tool should keep them rare; document `tmt check` as post-merge fixup.
- Does tmt.json carry repo config beyond `tools` (default lang, caps), or
  stay entries-only until a need appears?
- Usage evidence for promotion decisions: none for now (human judgment);
  revisit self-logging shims only if promotion decisions prove hard.

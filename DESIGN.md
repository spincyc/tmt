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

### Amendment 2026-07-29: the note store is local; aiq is the mirror

Original decision: candidate events lived only in aiq, and `tmt candidates`
read them back out of aiq's inbox. An audit showed the cost: with no aiq on
PATH, `tmt note` — the loop's opening move and the habit the whole design
exists to build — failed with `aiq-unavailable`, so a stranger's first
contact with the central idea was an error. aiq has no public release, and
the README installs only tmt.

Superseding decision: notes are recorded in untracked machine-local state
under `$(git rev-parse --git-common-dir)/tmt/notes.jsonl` (the state
placement already reserved above; `.tmt/` outside a git work tree), and
that store is what counting reads. aiq remains the optional upgrade: each
note is still mirrored to `aiq ingest` when aiq is present, and a mirroring
failure never fails the note. The sibling-with-seams decision is unchanged
in substance — neither system requires the other — but the direction of the
dependency is now honest, and the git-dir lookup runs without a subprocess
so the fail-open session hook cannot hang or depend on PATH.

Reconciliation came with it: a slug that is already a registered tool is
not a candidate. `tmt note` on such a slug reports that it is built instead
of recording another nudge, `tmt candidates` marks built slugs, and session
context omits them — otherwise the ambient layer degrades into standing
noise about work already done.

### Amendment 2026-07-29: containment before convenience

A symlink is not a licence to leave the repository. Every write path
resolves its target and refuses one landing outside the repository root
(`containment`, exit 3), and `tmt vendor` refuses a source tool that
resolves outside its source repo — an untrusted repository could otherwise
have tmt copy an arbitrary local file into your registry and stage it for
commit. `tmt.json` and `AGENTS.md` writes are staged and renamed, so an
interrupted save cannot truncate a committed file, and an in-repo symlink
survives the write instead of being replaced by a regular file.

Environment failures are no longer reported as tmt defects: unreadable or
undecodable files raise `io-error` (exit 3) rather than `internal` (exit
70), which stays reserved for real defects.

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

## Distribution (decided 2026-07-30: install from git, no PyPI)

tmt ships the way aiq does: `pipx install 'tmt-toolmaker @ git+<repo>@main'`,
or a tag for a stable pin. There is no package index release.

The alternative was finishing a PyPI publish — the machinery existed and
worked up to the point of upload, failing only because PyPI needs a trusted
publisher created by the account owner. It was dropped rather than completed
because tmt is a personal tool with a sibling that already distributes this
way, and a second channel is a second thing to keep honest: two version
truths, a publish credential, and a release step that can fail after a tag is
already public. Revisit if tmt is meant for people who should not need Git —
that, not convenience, is what PyPI buys.

Consequences accepted: installing requires Git and network access, `pipx
install --force` is the upgrade path, and a tag is the only stable pin — so CI
fails a tag whose commit declares a different version, because a tag-pinned
install would otherwise resolve to a version nobody named.

## Naming (decided: `tmt-toolmaker` as the distribution, `tmt` on the command line)

The distribution is `tmt-toolmaker` because teemtee's Test Management Tool
owns `tmt` on PyPI (aiq precedent: `aiq-workqueue`), which keeps the name free
if tmt is ever published. The console script stays
`tmt`: decided by the owner 2026-07-29, accepting that it collides on a
machine that also has teemtee's package installed. The habit this tool exists
to build is typed dozens of times a session and is quoted verbatim in every
repo's AGENTS.md fragment, so the short name is worth more than avoiding a
collision with a package this project's users are unlikely to have. Revisit
only if a real user reports the clash.

## tmt's own repo

Mirrors aiq conventions: stdlib-only Python 3.11+, src-layout, zero deps,
console entry `tmt.cli:main`, `make test/verify/ci`, versioned
`docs/contracts/`, JSON Schemas in `schemas/`, ≤150-word byte-verified
AGENTS.md, doc-tested README, Keep-a-Changelog. tmt's repo is itself
tmt-enabled (dogfood). CLI surface (all commands take `--json`):

`init | new | rm | rename | set | list | show | check | stage | note |
candidates | vendor | adopt | agents | context | integration`

Every command except `tmt context` (plain text by design) takes `--json`.
`make test`, `make verify`, and `make sanity-check` are the targets; there
is no `ci` target — CI runs `make verify` over the supported Python matrix.

Post-drive amendments (2026-07-29, after a full dogfood cycle): `tmt stage`
is the only sanctioned way to flip a tool's stage (promotion pre-runs the
stable battery; agents never hand-edit tmt.json); `tmt new` also scaffolds a
born-passing `tools/<id>.test` smoke; `tmt check` fails on used-but-undeclared
sibling composition; `tmt adopt` refuses non-stable tools; `tmt note` reports
the slug's running count and nudges `tmt new` at the threshold.

Guidance wiring: new `ai-guidance/15-tool-making.md` registered in
AI_GUIDANCE.md's ordered list (respect the 250-word entry budget); per-repo
AGENTS.md gains two lines pointing at tmt.json and `tmt new`.

### Amendment 2026-07-30: composition is detected by position, not by word

The undeclared-composition gate matched a sibling id as a bare standalone
word anywhere in a tool body outside full-line comments. The recorded reason
for scanning string literals was that path strings legitimately name
siblings — which is right, but the mechanism was wider than the reason.

New evidence: a tool named after an ordinary word is unusable. The scaffold's
own text contains `json`, so `tmt new json` failed every other tool in the
repository, and no `requires` declaration could fix it — the dependency does
not exist. `list`, `one`, and `check` fail the same way.

The gate now matches an id only in a path position: preceded by `/`, at most a
quote and whitespace between. That is precisely where the mandated adjacency
idiom puts it, so `tools/<id>` and both language idioms still match and prose
does not. This narrows a gate rather than widening one, and the cost is a
sibling invoked through some other construction going undetected — acceptable,
because such a construction already violates the composition rule the gate
exists to enforce.

## Settled (post-audit triage)

Decided with the owner after the audit; each was a live question and none
should be re-raised without new evidence. The first five were settled
2026-07-29, the last two 2026-07-30.

| Question | Decision | Why |
|---|---|---|
| Should a caller left broken by `tmt rename` be a gate failure? | No — `rename` reports `stale_callers` and warns; no new gate | A "declared `requires` must appear in the body" gate false-positives on wrapper-thin tools that reach a sibling indirectly, and the warning already fires at the one moment the break is introduced |
| Candidate threshold: per session or per repository? | Per repository, threshold 2, not configurable | Session identity is not something tmt has or wants; a config block is the ceremony this design exists to avoid. Revisit if the nudge proves noisy in practice |
| Windows support? | No; Linux and macOS only | `tools/<id>.test` files are `sh`, and the composition idiom is a POSIX path expression. Supporting Windows is a different product, not a port |
| `make verify` inside an extracted sdist runs a weaker battery (no git) | Accepted; it prints `SKIP check_tracked_paths, check_git_hygiene: not a git work tree` | A packager cannot have repository hygiene gates without a repository. Naming the skipped gates is honest; silently passing them would not be, and the 200-plus tests still run |
| Should the note store migrate old aiq-held notes? | No migration | Verified 2026-07-29: no repository under `~/git` held any `tmt`-sourced note event, so there was nothing to migrate |
| Should `stage` gain a `deprecated` value? | No | Every version that respects tmt's invariants collapses into a naming convention. It cannot be a failure — flipping the stage would break every dependent's build, so deprecation could never land separately from migration, which is `tmt rm` with extra steps. So it must be a warning; but `stable_gate_failures` drops warnings, so it would not stop anyone promoting into a dependency on a retiring tool. What remains is one warning line, which `tmt set purpose "DEPRECATED — use X"` already gives for free. Worse, `vendor` copies entries verbatim, so a foreign repo's retirement would land as a standing warning locally, and a `deprecated` that skipped the stable battery would make deprecating the cheapest way to silence a failing test. "Who still depends on this?" is already answered: `tmt rm` refuses and names every dependent. **Revisit** if a retirement is ever too large for one coherent commit |
| Can a tool be upgraded to a newer scaffold? | No; scaffolds are a starting point, not a live dependency | `tool.py` and `tool.sh` have never changed since 0.1.0a1 — all observed churn was `tool.test` while it was new — so the hard case has zero instances. The subset with the churn degenerates anyway: a real test has replaced the skeleton (nothing to merge into), and an unmodified one cannot be stable (nothing to preserve). A three-way merge needs a base that is not stored, and every place to store it is bad: machine-local state is absent in a fresh clone and in CI, a registry field means committing a template copy per tool into the ~15-tokens-per-tool discovery surface, and git history breaks on squash, rebase, import, and vendoring. Adding any entry field is also a hard forward-incompatibility, since an unknown key makes `registry.load` raise and every command fail on an older tmt. **Accepted risk**: a future template *correctness* fix leaves older tools silently carrying the bug — answered with a gate, which catches vendored and hand-written tools too, not with template provenance, which catches only scaffolds |

## Open questions

- Whether `tmt vendor` learns to fetch (URL sources, a `tmt outdated`
  sweep across vendored tools) given "vendoring, never linking" — the sync
  semantics are the hard part, not the transport.
- tmt.json merge conflicts on concurrent branches: sorted keys + one object
  per tool should keep them rare; document `tmt check` as post-merge fixup.
- Does tmt.json carry repo config beyond `tools` (default lang, caps), or
  stay entries-only until a need appears?
- Usage evidence for promotion decisions: none for now (human judgment);
  revisit self-logging shims only if promotion decisions prove hard.

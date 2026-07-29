# Concepts

tmt turns re-derived reasoning into durable executable knowledge.

```text
re-derivation noticed → note → candidates → new (draft) → check → stable → vendor/adopt
```

| Object | Purpose |
|---|---|
| Registry (`tmt.json`) | One committed manifest entry per tool; the discovery surface |
| Tool (`tools/<id>`) | A pure executable; `--help` always works |
| Long doc (`tools/<id>.md`) | Optional prose beyond `--help`, surfaced by `tmt show` |
| Test (`tools/<id>.test`) | Executable that exits 0; scaffolded by `tmt new`, the price of `stable` |
| Candidate | A recorded "re-derived X again" event, stored by aiq |
| Origin stamp | Provenance on a vendored copy: source repo, commit, sha256, remote url when known |

Agents run `tools/<id>` directly. tmt is required to make tools, never to run
them: one Read of `tmt.json` (~15 tokens per tool via the 80-character
`purpose`) replaces re-deriving the logic (~1,500 tokens), and the tool run
itself costs ~40.

## Lifecycle: escalating ceremony

The dominant failure mode of a tool registry is ceremony friction — if making
a tool costs more than one more re-derivation, agents defect and the registry
starves. So drafts are nearly free, and ceremony attaches at `stable`, which
is when composition and extraction start trusting the tool.

| Stage | Cost to enter | `tmt check` enforces |
|---|---|---|
| `draft` | `tmt new <id>` + paste the derived logic | registry validity, entry↔file parity, syntax lint, executable bit, `--help` smoke, `requires` resolve, no cycles, declared composition |
| `stable` | extend the scaffolded `tools/<id>.test`, run `tmt stage <id> stable` | draft gates + test exits 0 and differs from the unmodified scaffold + no draft dependencies + no hardcoded absolute paths |

Drafts may live indefinitely; the only penalty is exclusion from stable
composition. `tmt stage <id> stable` promotes a tool — it runs the full
stable battery first and refuses on any failure, so agents never hand-edit
`stage` — and `tmt check` is one line in the repo's existing verify target,
so a stale or lying registry is a build failure, not a discovery. The exact
gates are in the [registry contract](contracts/registry-v1.md).

## Language policy: Python-first

`tmt new` scaffolds Python (stdlib-only) unless `--lang sh` is given. The
cli-v1 `--json` contract is trivial in Python and error-prone in sh; one
default language means one lint battery, one test idiom, one composition
model. `sh` is the documented exception for wrapper-thin pipelines. Other
languages are permitted only when measured performance or a required feature
forces the escalation, recorded in the entry's `lang` field; `tmt check`
skips syntax lint for them but every other gate still applies.

Both scaffolds are born check-passing and exemplify the cli-v1 contract:
`--help`, and a `--json` stub emitting one compact key-sorted object with
`"v": 1` (the Python template also models the cli-v1 error envelope).

## Composition

A tool calls a sibling by adjacency, not by `PATH` or registry lookup:

| Lang | Idiom |
|---|---|
| sh | `"$(dirname "$0")/<dep>"` |
| python | `Path(__file__).parent / "<dep>"` |

and declares `<dep>` in its `requires` list. `tmt check` enforces the
declaration — a registered sibling id appearing in a tool's body without a
matching `requires` entry is a failure at every stage — keeps the graph
resolved and acyclic, and forbids a stable tool from requiring a draft — so
hardening pressure flows down the dependency graph, and composed tools
inherit every hardening their dependencies receive.

## Check-style tools

For tools that scan for problems, the recommended contract is `tmt check`'s
own: exit 0 when clean, exit 1 when findings are present, with `--json`
output identical in shape in both cases (the findings array is simply empty
when clean). Usage, state, and internal errors keep their cli-v1 categories
(2, 3, 70). The scaffolded test's commented skeleton shows the matching
assertion pattern for an expected exit 1:
`"$tool" ... && exit 1 || test $? = 1`.

## aiq seams

tmt and [aiq](../../aiq) are siblings: aiq owns work state (messages, tasks,
queue, journal); tmt owns durable executable knowledge. Neither requires the
other, and tmt talks to aiq only through its CLI — never its SQLite journal
or Python modules, both declared internal.

| Seam | Mechanism |
|---|---|
| Candidate signal | `tmt note <slug>` sends a v1 event envelope to `aiq ingest --event-json -` with `source: "tmt"` and a `"kind": "tmt-note"` content marker |
| Candidate readout | `tmt candidates` groups and counts those events from `aiq inbox list --json`; tmt stores no events itself |
| Tool-building as work | Crossing the candidate threshold files an aiq task; building the tool is queued, journaled work |
| Contracts | tmt adopts aiq [cli-v1](contracts/cli-v1.md) wholesale — one JSON protocol across aiq, tmt, and every generated tool |

aiq missing or failing degrades exactly two commands (`note`, `candidates`)
to `aiq-unavailable`; everything else still works.

## Forming the habit

The loop below only runs if agents remember it exists, and timing works
against them: guidance loads at session start, while the noteworthy moment —
"I just re-derived something" — happens mid-session. So the habit's presence
must be ambient, in three thin layers. A canonical AGENTS.md fragment
(`tmt integration print agents`) states the habit in under 50 words; `tmt
agents --write` installs it between owned markers and `tmt check` fails when
the installed copy goes stale, so the reminder in every repo stays current;
and a Claude Code `SessionStart` hook (`tmt integration install claude`)
runs `tmt context` to put the repo's tool list and noted candidates directly
into session context — the registry is visible before the first chance to
re-derive. Each layer is optional and reversible; see the
[integration contract](contracts/integration-v1.md).

## The loop

1. An agent notices re-derivation → `tmt note <slug> --note "context"`.
2. Recurrence → `tmt candidates` surfaces it; an aiq task is filed.
3. `tmt new <id>` scaffolds executable + registry entry, born check-passing;
   the agent pastes the logic and commits the smallest coherent diff.
4. The next session Reads `tmt.json` and runs the tool.
5. Edge cases are fixed in place (prefer editing over near-duplicates); the
   scaffolded test grows real assertions; `tmt stage <id> stable` promotes.
   Git history is the audit trail.

## Extraction tiers

Movement between tiers is vendoring — symmetric copying with provenance,
never linking. See the [vendoring contract](contracts/vendoring-v1.md).

| Tier | Home | How a tool gets there |
|---|---|---|
| 1 | The repo that derived it | `tmt new`; iterate in place |
| 2 | `tmt-lib` — an ordinary tmt-enabled repo containing only tools | `tmt adopt <id> --to ~/git/tmt-lib` (stable tools only); a human commits the promotion |
| 3 | tmt itself (tools about tool-making) | Ordinary pull request |

There is no pool concept: tier 2 is just another registry, so consuming repos
take copies with `tmt vendor ~/git/tmt-lib <id>`. Divergence after vendoring
is allowed — per-repo fitness beats shared-dependency correctness — and
`tmt check` reports upstream drift as a warning, never a failure. Promotion
is never automatic; there is no usage telemetry, only human judgment over
`tmt candidates` and Git history.

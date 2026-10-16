# Source-witness concept review (2026-10-16)

The two V11 false matches are removed and all four reviewed role disagreements
are corrected in the development replay. All **574 previously useful
case/declaration identities survive** through the installed v3 MCP. The 413
historical rows also retain their roles and ordering. Fresh V12 confirms all 70 returned rows are useful, but the strict qualification
**fails**: three semantic/context disagreements remain and one exact declaration
is absent from the bounded pool. Transport success is separate from that result.

## Corrected causes

| Frozen declaration | Source finding | Development decision |
|---|---|---|
| `main.rs::ResumeArgs`, 493–501 | Optional CLI `--task` omits a selector; it does not establish absent runtime task binding. | Irrelevant to continuing an unbound active workflow. |
| `workflow_status.rs::render_resume_text`, 4318–4553 | Chooses a concrete task and renders instructions; native continuation still requires `active_task`. | Irrelevant to the requested unbound continuation. |
| `hooks/background.rs::processor_admission`, 1137–1149 | Checks readiness. `before_attempt`, 1157–1166, charges and persists the attempt budget. | `supporting_context`, relationship `generic_prerequisite`. |
| `hooks/mod.rs::<module>`, provider gate | Its own `processor_receipt` path passes the captured client to the mandatory provider guard and propagates refusal. | `essential_helper`, relationship `domain_contribution`. |
| `hooks/mod.rs::receive`, 329–538 | Its own branch selects the recorded prompt episode and enters the inspected durable intake gate. | `entrypoint`, relationship `exposes_result`. |
| `hooks/mod.rs::<module>`, intake gate | Directly owns that query-specific branch and the durable episode path. | `implementation`, relationship `performs_operation`. |

Ranges above refer to the frozen corpus, not moving main-branch line numbers.
The [six source-bound corrections](concept-witness-20261016-corrections.json)
retain exact identities, reasons, hashes, own citations and inspected supporting
paths. Previous raw V11 labels remain unchanged and failed: 80/82 useful rows,
two irrelevant rows and four semantic/context disagreements. V11 is spent
development evidence, not a new qualification result.

## Process and mechanism

Before retrieval, a separate query-only author freezes `request_contract`:
requested operation plus exact quoted input, state, scope and result constraints.
Hints broaden recall without changing the query. The original query remains
authoritative even if that ledger is incomplete or mistaken.

Every relevant v3 judgment carries an own-behavior `witness`, a typed relationship
and a matched, source-bound check for every declared constraint. A generic
readiness prerequisite provides context. A module or handler can be semantic
through its inspected query-specific branch. Roles follow inspected behavior;
being mandatory, nearby or delegated does not determine the role by itself.
The server checks structure, bindings and declared consistency. It does not
independently decide whether the source judgment is true.

The frozen [review instructions](concept-witness-20261016-source-assessment-instructions.md)
and [context guidance](concept-witness-20261016-context-navigation-guidance.md)
were fixed before retrieval. The protocol is `operation-roles-v3`; packet schema
version remains 1. Reprepare after a role-contract change. Default wrappers keep
the whole query with no parsed constraints; they do not erase original terms.

The researcher ceiling is **5,000 characters**; the rendered prompt uses 3,271.
The canonical project workflow and compiled template are byte-identical at
9,981 UTF-8 bytes, below the unchanged 10,000-byte limit.

## Fresh V12 design

| Binding | Value |
|---|---|
| Planned queries | 24: 16 positive exact anchors, 8 bounded negative cases; top 5 |
| New positive owners | 16 distinct files; zero overlap with 124 excluded previous owners |
| Source revision | `f418b380bf191877f5903f5c85f483f5e0e86632` plus the two ordered reconstruction patches below |
| Frozen source | 699 files; tree SHA-256 `01946de15f9f7995b470961d7dfc72c7da648ddd050a3a75f595c992d68ca851` |
| Bound index | 343 files, 9,910 symbols; database SHA-256 `0f544583649ea76f0c207ef3e3b0c1129a11df91af2a933a46a704b8e8b14eee`; empty WAL |
| Installed binary | SHA-256 `603fdaab23045de14f3091e7c7e0946b5f88dd1eb73639740d06afcc585a9dd6` |
| Runtime | mmcg 3.3.1; MCP protocol 2025-11-25; 39 tools; v3 packets |
| Recall | Unchanged lexical/body/owned-scope candidates and ordering; four query-only hints per case |
| Primary assessment | Three separate agent contexts, eight cases each; no anchors, case kinds, native ranks or prior labels |
| Emitted-page audit | Three fresh contexts; exact identities in identity order; primary labels, roles, reasons and ranks withheld |

The [fixture](../fixtures/concept-relevance-20261016-independent-v12.json),
[source evidence](../fixtures/concept-relevance-20261016-independent-v12.source-evidence.json)
and [freeze](../fixtures/concept-relevance-20261016-independent-v12.freeze.json)
were retained before retrieval. The
[query-only hints](../fixtures/concept-relevance-20261016-independent-v12.hints.json)
and [contracts](../fixtures/concept-relevance-20261016-independent-v12.request-contracts.json)
are published separately from gold. Eight positive owners concern benchmark
contracts, metrics or artifact I/O; three concern CLI behavior, two persona
collection, and one each coverage ingestion, intake and profile delivery.
This distribution does not establish general query representativeness.

## Outcomes

| Fresh observed measure | Result |
|---|---|
| Independent audit | All 24 cases and all 70 emitted identities assessed |
| Useful relevance | 70/70 relevant; zero irrelevant and zero unknown emitted rows |
| Independent classes | 55 semantic, 15 context |
| Class disagreements | Three semantic → context; zero context → semantic |
| Intra-semantic role-name difference | One; retained without postflight correction |
| Positive queries with independent semantic results | 16/16 |
| Negative full and semantic pages | 8/8 empty |
| Frozen literal-name exact-anchor score | 13/16 |
| Postflight source-identity diagnostic | 15/16 declarations present; two qualified-name format mismatches, one actual pool omission |
| Strict qualification | **Failed**; no adjudication or label fitting applied |

The [independent source audit](concept-witness-20261016-independent-source-audit.json)
and [original exact score](concept-witness-20261016-exact-anchors.json) remain raw.
The [returned-page evidence](concept-witness-20261016-mcp-pages.json) retains all
client witnesses; source audits retain the independent judgments.

The three class disagreements concern `protocol.adapter_request` and the Codex
and Claude `StreamObserver.feed` methods. The request builder preserves a
verification operand but does not itself declare its schema. The feed methods
frame JSONL and delegate event-specific terminal transformation. The primary
reviewers classified these as contract/essential helpers; the independent
reviewer classified them as useful context. This exposes a remaining boundary
between constructing a value and declaring a contract, and between generic
framing and a domain transformation. Their raw labels were not changed to make
the fresh gate pass.

The [anchor diagnostic](concept-witness-20261016-anchor-diagnostics.json) separates
measurement format from search recall. `Root.write_new` and
`ProfileStore::set_source_sync_enabled` are emitted under leaf names at exactly
the frozen file and declaration line, and independently confirmed semantic.
`commands/audit.rs::validate_key_ids` is absent from the candidate pool. The query
still has independently semantic results through other declarations, but that
does not recover this exact anchor. The original 13/16 score and failed gate
remain unchanged; 15/16 is explicitly a postflight diagnostic, not a new
independent qualification. Further criterion/recall changes require a fresh set.

Raw MCP finish completed all 24 planned queries without transport or validation
failures. It returned 70 useful rows: 58 semantic and 12 context. Primary reviewers
classified all 1,826 candidates: 95 relevant, 202 irrelevant and 1,529 unknown;
the final top-5 pages truncate those 95 relevant assessments. All 24 cases remain
coverage-incomplete, with 524 source-omission records. Empty bounded pages do not
prove repository-wide absence. Independent emitted-page judgments are reported
separately from these raw client claims.

The [preservation proof](concept-witness-20261016-preservation.json) protects
413 historical rows, 76 current V10 rows, five human-clarified rows and all 80
independently useful V11 rows: **574/574 retained, zero losses, zero role errors**.
Only the four source-adjudicated V11 role changes are allowed. Both independently
rejected rows are absent. The [frozen inventory](concept-witness-20261016-protection-plan.json)
records every protected case/declaration identity.

Historical v1/v2 labels receive explicit compatibility witnesses (old reason as
behavior, typed role relationship and no newly asserted parsed constraints).
Their unchanged source bindings and returned pages are checked. Apart from the
six corrections, this is compatibility preservation, not fresh semantic
requalification of all 574 rows under v3.

## Runtime and deterministic checks

Four fresh stdio MCP sessions, with 412 logged requests plus their initialization
handshakes, prepare and finish the 178 development cases and 24 V12 cases. They use the installed binary selected by Codex configuration,
not native concept-review CLI calls. All request ledgers, packets, assessments,
responses, source, binary, database/WAL and configuration hashes remain bound.
The server invokes no model; external source reviewers are separate model work.

Only the configured `mmcg.command` changed; previous immutable binaries and all
other configuration fields remain intact. The current chat advertises a cached
39-tool v2 rubric. Its direct query probe hit the 10,000-ms work limit; an invalid
contract probe also failed. Neither establishes a successful v3 Desktop
connection. Positive runtime evidence comes from the user-accepted separate
source-bound stdio sessions. No Desktop restart is claimed.

| Check | Observed result |
|---|---|
| Final Python suite | 530 passed |
| Rust all targets | 1,938 passed; one child fixture intentionally ignored |
| Clippy | Passed with warnings denied |
| Rust formatting and release build | Passed |
| Artifact validator | 41 artifacts; zero errors and warnings |
| Prompt isolation | 27 passed outside sandbox |
| Code review | No actionable v3 regression found |

Initial sandbox-only Rust failures (loopback, descendant cleanup and a non-UTF-8
fixture) and three prompt-isolation cleanup errors remain retained separately;
the same complete checks passed outside sandbox. The first 529-test Python pass
predated one compatibility correction: sparse fixtures may omit optional
`distractors`, as accepted by the loader. A boundary test and the final 530-test
run cover that scorer fix. No fixture, criterion, query, hint or compiled Rust
input changed. The explicit superseding harness freeze predates all V12
retrieval.

The [final technical verification](concept-witness-20261016-verification.json)
checks all four sessions and 412 requests, raw/inline packet and response equality,
source/runtime/index/config bindings, cleanup, protected identities and the fresh
audit/scoring join. Its technical pass keeps the independent semantic gate
**failed**; it does not replace that gate with a successful transport result.

## Reproduce and inspect

Prerequisites: Git, Python standard library, Rust toolchain, an installed current
mmcg, and disposable source/index/output directories. Run from the repository
root. Never overwrite a retained result directory.

1. Archive source revision `f418b380bf191877f5903f5c85f483f5e0e86632` into a new directory.
2. Apply [concept-source-20261016.patch](concept-source-20261016.patch), then
   [concept-witness-20261016-source-supplement.patch](concept-witness-20261016-source-supplement.patch).
3. Initialize a disposable Git source inventory and add its files, then build
   an external index with `mmcg --index /absolute/new-index.db index /absolute/source`.
4. Follow the [operation-review commands](../benchmark/README.md#evaluate-operation-relevance-with-source-review)
   with the V12 fixture, hints and request-contract files. Keep gold away from
   reviewers. For MCP, use `mmcg_concept_prepare`, bound source reads and
   `mmcg_concept_finish` as defined in the [protocol reference](../../docs/reference/mmcg.md#local-symbol-concept-search).
5. Audit every returned identity in fresh contexts without primary labels or
   ranks. Check exact anchors independently from full-page useful precision and
   preserve unknowns, omissions, empty pages and failed-case denominators.

A fresh archive plus both patches reconstructs all 699 source files with the
exact original tree hash: [proof](concept-witness-20261016-source-reconstruction.json).
The initial single-patch attempt failed for ten files and remains
[preserved](concept-witness-20261016-source-reconstruction-initial.json). Source
mismatch requires reconstruction and a new index, not adjustment of expected
labels. New hosts may produce different SQLite/binary bytes; bind those new
artifacts to the same verified source rather than asserting byte-identical builds.

[Runtime/source/check bindings](concept-witness-20261016-runtime-bindings.json)
retain full hashes, source-code bindings including `test_runner.py`, installation
scope and observed command exits. Raw RPC traces, all candidate assessments,
producer scripts and older failed studies remain local under
`.mastermind/research/`; this compact publication does not make those entire
historical archives portable. Frozen JSON paths naming local originals are
provenance, not files claimed to exist in a fresh clone. Public counterparts
preserve the original bytes and hashes where published. Older statistical and
survey reports also reference retained local cache/repo-map inputs, which are
outside this change.

Queries are now observed regression data. Further qualification needs a newly
authored, frozen set. Source judgments are fallible model claims from separate
contexts using the configured model, without calibrated judge error or human
validation. [Author notes](concept-witness-20261016-author-notes.json) disclose
two incidental test-only declaration/wrapper exposures. Primary schema sampling
also exposed ordinary unit-test snippets; reviewers excluded them from evidence
and further body inspection. No previous relevance fixtures, gold labels or
judgments were exposed. Independent audit B incidentally encountered isolated test call-site and
`cfg(test)` declaration/import lines during searches; they were excluded from
evidence. Audit A and C reported no test-body/snippet exposure. All boundaries
are retained in the [review boundary record](concept-witness-20261016-review-boundaries.json).

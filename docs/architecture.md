# Lexora Architecture

## Status

This document describes the current evolving implementation. It is not a final platform design.

## Current Shape

```text
Next.js Web / HTTP client
    |
    v
FastAPI route
    |
    v
CaseWorkspaceService / PersistentLegalConversationService
    |
    +----> Lexora PostgreSQL adapters
    |          +----> cases, structured case profiles, and materials
    |          +----> Agent Platform Thread / Run / ordered event journal
    |          +----> North-owned LangGraph checkpoint tables
    |          +----> persisted material chunks and vectors
    +----> rag-core -> lexical/vector ranking and rank fusion
    +----> OpenAI-compatible Embedding provider
    +----> LegalKnowledgePort -> verified official statute repository
    +----> CaseLawKnowledgePort -> reviewed official guiding-case repository
    +----> North Agent Runtime -> OpenAI-compatible model
```

`apps/web` is an application-owned adapter. It uses generated OpenAPI types, same-origin API
rewrites, and TanStack Query for request state. Its conversation, material, citation, and responsive
workspace behavior belongs to Lexora; it does not import Dayboard business code or introduce a
shared UI package before a second stable UI contract exists.

Lexora owns the legal case model, prompt, material-reference policy, response shape, and user-facing
safety boundaries. North owns generic Agent assembly, execution, model integration, runtime events,
and in-process thread execution. `rag-core` owns framework-neutral document/Chunk contracts and
deterministic splitters plus framework-neutral lexical/vector ranking and rank-fusion primitives.
Lexora converts product materials into those contracts, persists deterministic chunks and vectors,
owns its query normalization and legal authority matching, and projects retrieved results back to
references such as `[M1:C1]`, `[L...:C...]`, and `[C...:S...]`.

## Agent Platform Boundary

Lexora now reuses Agent Platform's product-neutral Conversation, message, Run transition, event,
idempotency, and resumable-interaction contracts. This is its second real product consumer after
Dayboard.

Lexora maintains three application authorities. `conversation_threads` stores case-conversation
metadata and the last successfully committed LangGraph runtime thread and checkpoint ID. `agent_runs`
stores one execution lifecycle plus bounded list summaries. `agent_run_events` is a Thread-ordered journal;
`message.human` and `message.ai` rows are the conversation source of truth and assistant event
extensions hold citation presentations. There is no separate messages table and Run rows do not
store complete input/output bodies. Streaming token deltas are not persisted individually.

Agent Platform is not the complete AI core: North owns runtime execution and `rag-core` owns
retrieval primitives. Lexora owns its PostgreSQL ORM models and repository adapters, case ownership,
legal workflow, prompts, and response semantics. It imports the standalone package boundary only;
it does not import Dayboard application modules or tables.

## Recommended V1 Architecture

Lexora v1 should center on a structured legal-intake layer rather than on larger prompt bundles or a
full multi-agent graph. The recommended path is:

~~~text
CaseIntakeService
    +----> Matter / issue classifier
    +----> StructuredFactorExtractor AI discovers factors from current turn + prior case state
    +----> LearnedFactorCatalog      optional, versioned priors discovered from case corpora
    +----> SufficiencyGate           answer now vs ask 1~2 high-impact questions
    +----> RetrievalPlanner          statutes / interpretations / cases from factors
    +----> AnswerComposer            provisional analysis first, then bounded follow-up
~~~

This keeps one primary conversational Agent while moving the unstable part of legal consultation
into a product-owned case-understanding contract. The intake layer should not behave like a rigid
form. It extracts structured legal factors from free-form dialogue, carries them across turns, marks
them as asserted / denied / unknown / conflicting, and exposes only the small set of missing factors
that would materially change the current legal answer.

The main alternatives are explicitly deferred:

- full multi-agent orchestration as the default response path;
- archetype or prototype matching as the backbone of general legal consultation.

Both may appear later as specialized slices, but they are not the base architecture for the current
personal legal-analysis product.

## Reference Systems And Borrowed Patterns

Lexora should not copy any one external system wholesale. The useful path is to borrow concrete
strengths from different projects while keeping one coherent product contract.

| Reference | Worth borrowing now | Defer or avoid as the base path |
|---|---|---|
| structured-knowledge-extraction | bottom-up factor discovery from case corpora; AI-driven structured extraction; modular learned schema; missing-factor ranking | synthetic-data archetype clustering as the backbone of general legal consultation |
| LeCoDe | legal consultation should be evaluated as multi-turn fact gathering plus advice quality; key-fact and fact-importance framing | benchmark-style interaction loops directly in product UX |
| DLawBench | separate client belief from legally material fact; explicitly test information gathering and grounded memo writing | turning every conversation into a long lawyer interview regardless of user goal |
| FactFiller | dynamically generate bounded follow-up questions for vague users; tie questions to downstream legal retrieval | full questionnaire-first interaction before any useful provisional answer |
| JurisMA / From Query to Counsel | legal element graph thinking: entities, events, intents, legal issues; dynamic routing plus statutory grounding | full multi-agent decomposition before the intake and retrieval contracts are stable |
| ELLA | show only cited authorities and cases as user-visible evidence cards; use evidence presentation to improve trust | making article similarity or manual article selection the primary workflow |
| ChatLaw | SOP-style decomposition of legal work; domain-specific legal reasoning assets; Chinese legal assistant precedent | large model-centric platform complexity or broad multi-agent orchestration as v1 |
| NyayaAI | clean split between intake, research, strategy, drafting, compliance; SSE timeline and eval mindset | five-agent routing as the default answer path for the current personal product |
| Claude for Legal | narrow workflow agents, conservative defaults, source attribution, human-review gates | assuming attorney-review workflow or enterprise legal operations as the personal-user baseline |

The intended borrowing sequence is:

~~~text
now
  -> structured factor intake
  -> sufficiency gate
  -> grounded retrieval
  -> cited evidence cards

later
  -> domain workflows
  -> optional specialist agents
  -> questionnaire refinement
  -> archetype modules for narrow domains
~~~

## Immediate Implementation Order

The next implementation slice should be built in this order:

1. Dynamic StructuredFactorExtractor
2. CaseFactorProfile state merge
3. SufficiencyGate
4. RetrievalPlanner
5. Case-corpus FactorDiscoveryPipeline
6. Versioned LearnedFactorCatalog
7. AnswerComposer adjustments

The order matters. Lexora should not keep expanding prompts before these contracts exist.
Retrieval quality, follow-up quality, and final answer structure should all be driven by the factor
profile and sufficiency gate rather than by free-form model behavior.

## Retrieval Evolution

For every conversation turn, a Lexora-owned middleware requires one successful
`prepare_legal_turn` call before the model may produce a final response. The structured call classifies
the turn, extracts only user-stated case facts, identifies one legal issue, supplies up to three focused
authority queries, dynamically defines relevant factual factors, and selects at most two unknown
outcome-changing factor keys. For legal questions the tool runs
the raw user question and focused queries through verified-statute retrieval; social turns skip RAG.
The Agent may then use separate case-material, statute, and guiding-case tools for supplemental searches.
Tool closures inject the trusted case and user context, while the model never supplies case or user IDs.
Selected tools rank persisted chunks lexically and semantically and fuse their rankings. Statute chunks
preserve their `编/章/节/条` hierarchy; case-law chunks preserve named decision sections. Without an
embedding configuration all paths retain deterministic lexical retrieval. A structured full-case
analysis still receives all submitted material chunks because completeness, rather than
question-specific recall, is its contract.

This follows DeerFlow's middleware boundary without copying its complete agent stack: orchestration
constraints wrap model calls while domain work remains in tools. North still owns the loop and
Checkpointer; Lexora owns the legal turn schema, preparation middleware, retrieval plan, and answer
contract.

Vectors use PostgreSQL's native dimension-flexible `vector` type. The current corpus size makes an
exact database-side vector scan deterministic and sufficient for now; an approximate database index
is deferred until corpus size and embedding dimension justify it. Lexora imports `rag-core`, not
`rag-langchain`, because the latter remains an application
with its own API, persistence, security, Agent, and Run lifecycle.

`rag-core` is versioned in this repository under `packages/rag-core` so a standalone Lexora clone
contains its complete retrieval foundation. It remains a separate Python package with independent
tests and must not acquire legal, database, provider, authorization, or Agent-runtime concerns.

Online legal-authority retrieval has stricter resource constraints than offline evaluation. Vector
distance and Top-K candidate selection must execute inside PostgreSQL/pgvector. The application may
scan lightweight statute text for deterministic lexical candidates, but it must not select the full
corpus embedding column or materialize all vectors in Python. Only the bounded union of lexical and
vector candidates may be hydrated for final rank fusion. Query fan-out and concurrency must both
have explicit limits. The current limits are 10,000 lightweight lexical chunks, 500 vectors for the
test-only non-PostgreSQL fallback, Top-K 50, four concurrent database retrievals, four authority
queries per legal turn, and two concurrent authority queries within that turn. Capacity beyond a
hard limit must introduce an indexed retrieval path; it must not silently restore a full-corpus
application scan. These are correctness constraints because violating them can exhaust the host, not
merely retrieval optimizations. See
[the 2026-08-11 memory-thrashing incident](incident-2026-08-11-memory-thrashing.md).

The expected evolution is:

```text
Lexora application
    |
    +----> North
    +----> Agent Platform       Conversation / Run lifecycle (active)
    +----> rag-core             Chunk, lexical/vector ranking, fusion (active)
    +----> LegalKnowledgePort   verified statute retrieval (active)
    +----> CaseLawKnowledgePort reviewed guiding-case retrieval (active)
                 |
                 +----> application-owned storage/retrieval adapters
```

The first external workflow is statute retrieval from a versioned `lvyan-lawtext` snapshot. Synced
versions remain unavailable to conversations until human review. Retrieval preserves the official
URL and source status, and its Recall@K/MRR evaluation is separate from answer quality.

The first case-law workflow downloads a curated manifest from the Supreme People's Court's official
guiding-case pages. It validates the final host, parses named decision sections, and stores each
downloaded version as pending. Only approved, active versions are retrieved. Case-law context may
support similarity and difference analysis; it never establishes user facts or guarantees the same
outcome.

## Structured Case Profile

The personal workspace persists a user-editable `CaseProfile` on each legal case. It contains case
type, parties, claims, key facts, disputed issues, evidence notes, and missing information. The
required `prepare_legal_turn` tool stages concise facts explicitly stated or confirmed by the user and
replaces missing information with questions resolved from the current turn's unknown factor keys. Tool closures retain
trusted case context; the model never supplies a case or user identifier. Updates remain staged in
memory until the Run completes, then commit in the same transaction as the assistant message. Failed
or cancelled Runs leave the durable profile unchanged.

The profile is application-owned legal workflow data, not a `rag-core`, North, or Agent Platform
concern. Conversation prompts and retrieval queries may use it as user-stated context, while the
system still labels it as unverified case data and never treats it as legal authority or proof. It is
a projection of case state for inspection and correction, not a required form or a separate
generation workflow. Conversation history remains the durable record.

The profile is factor-oriented without requiring a hand-written list of legal fields. On each turn the
model discovers only factual dimensions that materially affect the current issue, emits their stable
keys and metadata through a bounded structured tool, and reuses existing keys from the case profile.
Application code validates structure, merges state, and bounds follow-up questions; it does not match
legal keywords or decide which facts matter. The intended evolution is:

~~~text
current dialogue + current case profile
    +----> AI-discovered case factors
    +----> deterministic state merge / sufficiency gate
    +----> optional learned factor priors from versioned case-corpus discovery
~~~

CaseFactorProfile is not an AI-only analysis artifact. It should be treated as product-owned case
state with AI-assisted proposals:

- the model may propose factor updates from the current turn;
- application code merges, deduplicates, and marks state transitions;
- only successful runs commit updates;
- legal conclusions, probability estimates, and retrieved authorities do not become factors;
- user statements, denials, conflicts, and material-supported facts remain distinguishable.

In other words, AI helps extract and normalize the case state, but the profile itself is a bounded
domain object, not a free-form model summary.

## Conversation Experience Contract

The primary workflow is chat-first. The product Thread owns conversation identity while a committed
runtime thread owns LangGraph state; every turn still creates an independent Run. Before the first
successful checkpoint, each attempt uses its Run ID as an isolated runtime thread and bootstraps only
completed persisted message pairs. Later turns reuse the committed runtime thread, resume the last
successful checkpoint, and add only the new user turn. Failed or cancelled partial checkpoints never
advance either Thread pointer. The current case profile remains product-owned context, and the Agent may
retrieve private evidence, verified legal authorities, or reviewed cases through separate tools.
The preparation schema limits each turn to two prioritized decision factor keys. The sufficiency gate
accepts only factors present in the merged profile and filters factors already asserted, denied, or
conflicting before returning their canonical questions. The final response must answer from prepared
facts and authorities before asking the remaining questions; missing facts do not block a bounded
provisional analysis.

Factor discovery has two different lifecycles. Online extraction creates and updates factors scoped to
one user's case, so an unseen matter type remains usable immediately. Offline discovery reads batches
of versioned judgments, lets the model freely identify candidate decision factors, and performs a
second model pass for merge, deduplication, and normalization. Reviewed results are published as a
versioned `LearnedFactorCatalog` and supplied to online extraction as priors, never as mandatory fields.
One conversation cannot mutate the global catalog. Existing guiding-case ingestion can supply reviewed
examples, but a representative judgment corpus, provenance controls, discovery evaluation, and a
publish/reject workflow are required before the catalog may influence production conversations.
Offline model work uses a persistent project-wide token ledger. Its 100-million-token limit counts
actual input and output across every discovery run rather than resetting per command. Content-addressed
batch reservations and case hashes make retries idempotent; completed work must be reused before an
expanded sample can schedule new work.
Prototype clustering and quantitative outcome prediction remain deferred until corpus quality and bias
evaluation justify them. Dataset sources, provenance requirements and the first acquisition plan are
specified in [Factor Discovery Data](factor-discovery-data.md).

The browser submits one streaming HTTP request per turn. North `messages` events become incremental
assistant text; the final `values` event completes the Run without replaying that text. The user
message is persisted once at submission and the assistant message once at successful completion.
The browser does not poll the Run or refetch messages while text is streaming; it refreshes durable
state once after completion.

Retrieved authorities are candidates, not citations. Lexora persists and returns only references
that the final answer actually cites, in first-use order. Durable messages retain stable internal
references for provenance, while the presentation layer maps statute and case-law references to
compact `[1]`, `[2]` markers and hides unused legacy citation cards.

## Dependency Rules

- `domain` has no FastAPI, North, database, or provider imports.
- `application` depends on domain and declares ports.
- `infrastructure` implements application ports and may depend on North.
- `api` maps HTTP to application use cases and owns no legal analysis rules.
- Lower-level packages never import Lexora.
- Case materials and retrieved documents are untrusted data, not instructions.

## Current Limits And Next Slices

Completed: case workspace persistence, private material ingestion, persisted lexical/vector chunks,
hybrid retrieval, and durable Thread/Run/event-journal storage through product-owned adapters.

Completed: official North PostgreSQL checkpointing now restores Agent state from a committed runtime
thread and checkpoint while each turn retains a distinct product Run lifecycle. Lexora Alembic
excludes the four North-owned checkpoint tables from product schema comparison.

Completed: eight statute sources have been synchronized, structurally verified, and approved. The
set includes the current Criminal Law, Criminal Procedure Law, and theft judicial interpretation.
Its evaluation covers 2,445 article chunks and 23 grounded queries. The deterministic exact-plus-
lexical path reaches Recall@3/5 of 1.0 and MRR@5 of 0.8768. The earlier five-source, 17-query BGE-M3
hybrid baseline reached Recall@3/5 of 1.0 and MRR@5 of 0.9412.

Completed: the initial seven-source Supreme People's Court guiding-case set has a separate storage,
review, retrieval, prompt, citation, and UI path. Its 52 chunks and seven grounded lexical queries
currently reach Recall@1/3/5 and MRR@5 of 1.0; this small-set result is not answer-quality evidence.

Completed: each persistent case conversation exposes the latest Agent Platform Run status and allows
the personal user to cancel queued or running analysis. A cancelled run cannot later be overwritten
by a late model response, and the browser aborts its waiting request after the server records the
cancellation.

Completed: explicit facts supplied during conversation can be staged through the Lexora case-memory
tool and committed with a successful Run. Repeated facts are merged without duplication, resolved
information is removed by replacing the outstanding missing-information state, and the UI surfaces
a lightweight profile update state.

1. Add update checks against primary sources while retaining human confirmation.
2. Surface conflicting or uncertain case-state changes for explicit user confirmation.
3. Expand case retrieval beyond the initial guiding-case slice using measured user needs and a
   source with stable official provenance.
4. Add startup recovery and idempotent HTTP submission for interrupted requests.
5. Authentication and authorization before any multi-user release.

Each slice must remain usable and testable on its own. Do not begin by copying the complete RAG
application or by designing one giant legal schema up front. Grow a stable core plus measured domain
extensions.

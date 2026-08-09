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
    |          +----> Agent Platform Conversation / Run / messages
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

Agent Platform is not the complete AI core: North owns runtime execution and `rag-core` owns
retrieval primitives. Lexora owns its PostgreSQL ORM models and repository adapters, case ownership,
legal workflow, prompts, and response semantics. It imports the standalone package boundary only;
it does not import Dayboard application modules or tables.

## Retrieval Evolution

For a conversation turn, the Agent receives three Lexora-owned tools: case-material search, verified
statute search, and reviewed guiding-case search. It decides whether and which tools are needed from
the user's intent; greetings and other non-legal turns do not automatically run retrieval. Tool
closures inject the trusted case and user context, while the model supplies only a query. Selected
tools rank persisted chunks lexically and semantically and fuse their rankings. Statute chunks
preserve their `编/章/节/条` hierarchy; case-law chunks preserve named decision sections. Without an
embedding configuration all paths retain deterministic lexical retrieval. A structured full-case
analysis still receives all submitted material chunks because completeness, rather than
question-specific recall, is its contract.

Vectors use PostgreSQL's native dimension-flexible `vector` type. The personal-case limit makes an
exact in-application scan deterministic and sufficient for now; an approximate database index is
deferred until corpus size and embedding dimension justify it. Lexora imports `rag-core`, not
`rag-langchain`, because the latter remains an application
with its own API, persistence, security, Agent, and Run lifecycle.

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

The personal workspace now persists a user-editable `CaseProfile` on each legal case. It contains
case type, parties, claims, key facts, disputed issues, evidence notes, and missing information.
The profile is application-owned legal workflow data, not a `rag-core` or Agent Platform concern.
Conversation prompts and statute queries may use it as user-confirmed context, while the system still
labels it as unverified case data and never treats it as legal authority or proof. It is a projection
of case state for inspection and correction, not a required form or a separate generation workflow.
Conversation history remains the durable record. Future background extraction may update low-risk
state, but conflicts and uncertain interpretations must be surfaced for user confirmation.

## Conversation Experience Contract

The primary workflow is chat-first. Each turn receives recent persisted messages and the current case
profile, then the Agent may retrieve private evidence, verified legal authorities, or reviewed cases
through separate tools. The model must reuse already supplied facts, avoid repeated questions, and ask
at most three prioritized clarification questions when a missing fact materially changes the analysis.
Once context is sufficient, it should answer the user's immediate question before expanding into
structured analysis.

The browser submits one streaming HTTP request per turn. North `messages` events become incremental
assistant text; the final `values` event completes the Run without replaying that text. The user
message is persisted once at submission and the assistant message once at successful completion.
The browser does not poll the Run or refetch messages while text is streaming; it refreshes durable
state once after completion.

## Dependency Rules

- `domain` has no FastAPI, North, database, or provider imports.
- `application` depends on domain and declares ports.
- `infrastructure` implements application ports and may depend on North.
- `api` maps HTTP to application use cases and owns no legal analysis rules.
- Lower-level packages never import Lexora.
- Case materials and retrieved documents are untrusted data, not instructions.

## Current Limits And Next Slices

Completed: case workspace persistence, private material ingestion, persisted lexical/vector chunks,
hybrid retrieval, and durable Conversation/Run/message storage through product-owned adapters.

Completed: the initial five-source statute set has been synchronized, structurally verified, and
approved. Its evaluation covers 1,617 article chunks and 17 grounded queries. The deterministic
exact-plus-lexical path reaches Recall@3/5 of 1.0 and MRR@5 of 0.8725. With the configured BGE-M3
vectors, hybrid retrieval reaches Recall@3/5 of 1.0 and MRR@5 of 0.9412.

Completed: the initial seven-source Supreme People's Court guiding-case set has a separate storage,
review, retrieval, prompt, citation, and UI path. Its 52 chunks and seven grounded lexical queries
currently reach Recall@1/3/5 and MRR@5 of 1.0; this small-set result is not answer-quality evidence.

Completed: each persistent case conversation exposes the latest Agent Platform Run status and allows
the personal user to cancel queued or running analysis. A cancelled run cannot later be overwritten
by a late model response, and the browser aborts its waiting request after the server records the
cancellation.

1. Add update checks against primary sources while retaining human confirmation.
2. Maintain case state incrementally during conversation and surface only conflicts for confirmation.
3. Expand case retrieval beyond the initial guiding-case slice using measured user needs and a
   source with stable official provenance.
4. Add startup recovery and idempotent HTTP submission for interrupted requests.
5. Authentication and authorization before any multi-user release.

Each slice must remain usable and testable on its own. Do not begin by copying the complete RAG
application or by designing a universal legal schema.

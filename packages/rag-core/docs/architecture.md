# rag-core Architecture

## Dependency Direction

```text
applications and adapters -> rag-core
rag-core -X-> applications, frameworks, storage, or providers
```

The package owns deterministic, domain-neutral behavior. This currently includes document splitting,
in-memory lexical/vector candidate ranking, cosine similarity, and reciprocal-rank fusion.
Applications own authentication, tenant and resource scope, persistence, ingestion orchestration,
retrieval policy selection, stop terms, domain enrichment, citations, prompts, and presentation.

## Admission Rule

A new capability enters `rag-core` only when:

1. at least two real applications use the same invariant;
2. the contract can be expressed without product vocabulary;
3. it has deterministic tests independent of infrastructure;
4. authorization, storage, provider, and domain policy remain outside the core.

The document/chunk slice was extracted from `rag-langchain` only after Lexora required the same
boundary. Retrieval slices followed only when both applications needed the same framework-neutral
tokenization, cosine, and fusion behavior. Legal numbering, SQL candidate filtering, embedding
providers, LangChain adaptation, and Lexora's material policy remain application extensions.

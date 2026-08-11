# rag-core

`rag-core` provides framework-neutral document, chunk, and retrieval contracts plus deterministic
splitting and ranking primitives. It is versioned with Lexora so a standalone clone contains the
complete retrieval foundation, while remaining an independently testable Python package.

The active extraction slices include:

- parsed-document, block, and chunk-draft contracts;
- validated chunking policies;
- replaceable token-estimator protocols;
- recursive and hierarchical deterministic splitters;
- an explicit splitter registry;
- retrieval document and hit contracts;
- configurable CJK/Latin query tokenization;
- deterministic lexical scoring and ranking;
- cosine vector ranking and reciprocal-rank fusion.

It deliberately does not include parsers, databases, embedding providers, authorization, legal
numbering, product stop-word policy, prompts, or Agent runtime behavior. SQL/vector adapters and
product retrieval orchestration remain with Lexora.

```bash
uv sync
uv run ruff check .
uv run pytest -q
```

See [the ownership rules](./docs/architecture.md) before extending the package.

# Factor Discovery Data

## Purpose

Lexora uses case data for two different purposes:

1. user-facing case retrieval and citation;
2. offline discovery of factual factors that materially affect legal analysis.

These paths may share normalized case text, but they do not share the same publication threshold.
Only reviewed official cases may be shown as authorities. Research datasets may help discover and
evaluate factor schemas, but they are not automatically valid user-facing citations.

## Source Tiers

| Tier | Source | Intended use | User-visible authority |
|---|---|---|---|
| A | [People's Courts Case Database](https://rmfyalk.court.gov.cn/), Supreme People's Court guiding cases, Gazette and officially published typical cases | production retrieval, reviewed factor discovery, schema validation | yes, after source and content review |
| B | [CAIL2018](https://github.com/china-ai-law-challenge/CAIL2018) | large-scale criminal factor discovery and extraction evaluation | no |
| B | [LeCaRDv2](https://github.com/THUIR/LeCaRDv2) | criminal case retrieval evaluation, factor relevance and stability checks | no |
| C | the synthetic cases in `structured-knowledge-extraction` | pipeline tests and deterministic development fixtures | never |

The People's Courts Case Database is the preferred production source because it contains guiding
cases and reference cases reviewed by the Supreme People's Court. The official database opened to
the public in February 2024 with 3,711 cases according to the
[official launch notice](https://www.court.gov.cn/zixun/xiangqing/426222.html); the Supreme People's
Court [reported 5,040 cases](https://www.court.gov.cn/zixun/xiangqing/471041.html) as of 2025-07-15,
covering criminal, civil, administrative, enforcement and state-compensation matters. The
[official operating rules](https://www.court.gov.cn/fabu/xiangqing/431662.html) state that the
database contains guiding cases and reviewed reference cases for public query, use, study and
research.
There is no documented public bulk export contract in the sources reviewed for this design. Lexora
must therefore begin with explicit source manifests and approved connectors, preserve the official
URL, and avoid bypassing login, access controls, rate limits or anti-automation measures.

CAIL2018 contains criminal fact descriptions and labels for relevant articles, accusations and terms
of imprisonment. Its published description reports 2.68 million criminal documents across 202
charges. It is useful for bottom-up factor discovery at scale, but is old, criminal-only, optimized
for judgment-prediction research and insufficient as a current legal authority.

LeCaRDv2 contains 800 query cases and 55,192 candidate cases drawn from a larger criminal corpus,
with relevance judgments from multiple criminal-law annotators. It is the better starting point for
case-retrieval evaluation and for checking whether discovered factors improve retrieval. It is not a
replacement for current official cases.

Both research repositories contain MIT license files for their repository contents. Before storing,
redistributing or using the downloaded case data outside internal research, the dataset terms and
underlying judgment-text rights must still receive a separate review. A code-repository license must
not be assumed to grant every right in the underlying documents.

## Coverage Decision

The first discovery corpus should be split by use case:

```text
criminal
  -> CAIL2018 sample for discovery
  -> LeCaRDv2 for retrieval/stability evaluation
  -> official case database for current-rule validation and citations

civil / labor / family
  -> official case database + Gazette + official typical-case releases
  -> begin with reviewed issue-specific samples
  -> add a licensed corpus later if broader statistical coverage is required
```

Unknown or weakly covered matter types remain usable because the online Agent can discover
case-scoped factors dynamically. Corpus coverage improves consistency; it is not a prerequisite for
answering a new type of question.

## Storage And Provenance

Datasets are external data and must not be committed to this repository. A dataset version should be
stored under an ignored path such as:

```text
storage/factor-discovery/
  <dataset>/
    <version>/
      manifest.json
      raw/
      normalized/
      discovery-runs/
```

Each manifest records at least:

- dataset name and version;
- original publisher and download URL;
- acquisition time and SHA-256;
- documented license or usage terms and review status;
- permitted scopes: research, evaluation, production retrieval, user-visible citation;
- coverage by case type, date and court level;
- normalization code version and rejected-record counts.

Raw text is immutable. Normalized records retain source IDs and hashes. Personally identifying fields
that are unnecessary for factor discovery should be removed before an LLM call. Dataset text is
untrusted input and cannot supply instructions to the discovery model.

## Discovery And Publication

The offline pipeline follows the bottom-up pattern from `structured-knowledge-extraction`:

```text
versioned case sample
  -> batch-level free factor discovery by LLM
  -> second-pass merge, deduplication and normalization
  -> factor extraction over a held-out sample
  -> stability, coverage and retrieval-impact evaluation
  -> human review
  -> immutable LearnedFactorCatalog version
```

A catalog entry records the factor key, neutral label, value type, canonical question, applicable
issues, supporting case references, discovery sample, stability metrics and catalog version. Legal
conclusions, outcome probabilities and statutes are not factors.

Publication requires:

- reproducible source manifests and immutable input hashes;
- separate discovery and evaluation samples, preferably split by time;
- factor stability across multiple batches and prompts;
- rejection of duplicate, conclusory, discriminatory or leakage-prone factors;
- review against current official cases and current law;
- explicit approval before the catalog becomes an online extraction prior.

One user conversation may update only its own `CaseFactorProfile`. It may produce a candidate for a
future discovery run, but it cannot mutate a published catalog directly. Catalog rollback is performed
by switching the active immutable version.

## Initial Acquisition Plan

1. Download CAIL2018 outside Git and verify the archive hash; start with a stratified criminal sample,
   not the full 2.68-million-document corpus.
2. Acquire LeCaRDv2 and preserve its expert relevance labels as a fixed retrieval evaluation set.
3. Expand the existing official-case manifest from seven guiding cases to selected criminal, labor,
   marriage-family and contract issues in the People's Courts Case Database.
4. Run factor discovery first on one bounded criminal slice and compare discovered factors across at
   least three independent batches.
5. Do not publish a learned catalog until the factor extraction and follow-up behavior beat the current
   dynamic-only baseline on a held-out conversation evaluation set.

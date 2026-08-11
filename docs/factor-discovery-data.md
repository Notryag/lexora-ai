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
| B | [CAIL2022-LCR](https://github.com/china-ai-law-challenge/CAIL2022) | criminal case retrieval evaluation; query/candidate relevance | no |
| B | [LeCaRD-Elem](https://aclanthology.org/2024.findings-acl.139/) | legal-element extraction and retrieval-design reference | no |
| B | [STARD](https://github.com/oneal2000/STARD) | real consultation-to-statute retrieval evaluation | no |
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

Dataset publication year is not judgment recency. For example, inspected CAIL2022-LCR query records
include 2019 case facts. CAIL2022-LCR and LeCaRDv2 are newer retrieval benchmarks than CAIL2018, but
they do not establish that their underlying judgments or legal rules are current. LeCaRD-Elem is a
2024 element-aware retrieval dataset built on LeCaRD, while STARD is a 2024 benchmark containing 1,543
real non-professional consultation queries and statute relevance labels. These improve factor and
retrieval evaluation; current-law validation still comes from reviewed official statutes and current
People's Courts Case Database entries.

Several research repositories contain MIT license files for their repository contents. Before storing,
redistributing or using downloaded case data outside internal research, the dataset terms and underlying
judgment-text rights must still receive a separate review. A code-repository license must not be assumed
to grant every right in the underlying documents.

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

1. Download CAIL2018 outside Git and verify the archive hash; treat it only as a sampling pool and
   never send the full 2.68-million-document corpus to a model.
2. Acquire LeCaRDv2 and preserve its expert relevance labels as a fixed retrieval evaluation set.
3. Expand the existing official-case manifest from seven guiding cases to selected criminal, labor,
   marriage-family and contract issues in the People's Courts Case Database.
4. Run factor discovery first on one bounded criminal slice and compare discovered factors across at
   least three independent batches.
5. Do not publish a learned catalog until the factor extraction and follow-up behavior beat the current
   dynamic-only baseline on a held-out conversation evaluation set.

## Cost And Sampling Limits

The first executable experiment still covers one issue only. Its default per-plan budget is:

| Limit | Default |
|---|---:|
| discovery sample | 750 cases |
| held-out evaluation sample | 200 cases |
| total unique cases sent to an LLM | 950 cases |
| discovery / merge / extraction model calls | 100 calls |
| per-plan input ceiling | 10,000,000 tokens |
| per-plan output ceiling | 1,000,000 tokens |
| project-wide input + output ceiling | 100,000,000 tokens |

The 100-million-token ceiling is cumulative across all factor-discovery runs, models, retries and
stages. It is not recreated for each command. A SQLite ledger at
`storage/factor-discovery/token-budget.sqlite3` persists settled usage and outstanding reservations.
Every reservation uses the content-addressed batch cache key as its unique key. Repeating the same
reservation is idempotent, settling the same provider usage twice does not double count, and reopening
the ledger cannot change its configured limit. Input and output tokens are added together.

Cases are stratified by the available outcome labels and relevant metadata before sampling. Discovery
batches are packed by estimated tokens rather than by a fixed document count. Only the fact and
reasoning fields required by the current experiment are sent; full documents, party identities and
irrelevant procedural boilerplate are excluded.

The future CLI must default to a dry run that prints the dataset version, sampling seed, selected case
count, estimated token usage and configured hard limits. Execution requires an explicit flag. It must
stop before any case-count, call-count, input-token or output-token limit is exceeded. Provider cost may
also be configured as an additional hard limit once the selected model has a versioned price entry;
token limits remain authoritative when price metadata is missing or stale.

Every batch result is cached by dataset hash, normalization version, prompt version, model identifier
and ordered input hashes. Case facts are deduplicated by their full SHA-256 before sampling. A retry or
resumed run must reuse settled batch keys and their cached results. The future executor must reserve a
batch before its provider call and settle actual input plus output usage afterward; a settled key must
never call the provider again. Increasing a limit creates a new run plan, and the executor must filter
already completed case-stage keys so only new work is sent. No automatic schedule may enlarge these
budgets.

The initial 750/200 split is an engineering baseline, not a claim of statistical sufficiency. Expansion
requires a recorded comparison showing unstable factors, inadequate coverage, or measurable retrieval
or conversation gains that justify the additional model cost.

## Current Implementation

The repository currently implements the non-billable planning stage:

```bash
uv run lexora-factor-discovery \
  /path/to/cases.jsonl \
  --format cail2018 \
  --name cail2018 \
  --version 2018-sampled \
  --issue 盗窃罪 \
  --model planned-model-id
```

The command streams JSONL records, stops at the configured scan or candidate-pool limit, normalizes
only the selected issue, creates deterministic outcome-stratified discovery and evaluation samples,
packs batches by conservative token estimates, and emits content-addressed cache keys. It never calls
an LLM and has no execute mode yet.

`within_budget` reports only whether the planned cases, calls and tokens fit the hard limits.
`execution_ready` is stricter: it also requires a previously verified dataset SHA-256 and complete
discovery/evaluation sample sizes, plus an acquisition manifest whose dataset license review is
`approved` for model processing. Supplying `--sha256` records an acquisition-time verification; the
planner deliberately does not rescan a potentially gigabyte-sized file to recompute it. When present,
`<dataset>.source.json` is loaded automatically as the acquisition manifest.

The source registry is stored in
`src/lexora_ai/resources/factor_discovery_datasets.json`. CAIL2018 is currently recorded as a
984,551,626-byte remote archive with `acquisition_status=not_downloaded` and
`license_review_status=pending`. No external research dataset is shipped in the application image.

CAIL2018 does not need to be downloaded in full. The source manifest records the ZIP central-directory
metadata for its validation member. The bounded acquisition command downloads only that member:

```bash
uv run lexora-factor-dataset \
  storage/factor-discovery/cail2018/2018-all/raw/data_valid.json \
  --dataset cail2018 \
  --member validation-sample-pool
```

The connector requires an allowlisted HTTPS host, matching archive size and ETag, an exact local ZIP
header, `206 Partial Content`, matching compressed/uncompressed sizes, and a matching CRC. The download
and decompression ceilings are 16 MiB and 64 MiB respectively. It refuses a server that ignores Range
requests and never falls back to downloading the complete archive.

An acceptance dry run against the 66 synthetic records from the local
`structured-knowledge-extraction` project scanned 66 records, selected 24 theft cases as a 16/8 split,
and estimated three future model calls and 7,451 input tokens. Actual model calls and cost were zero.

The first real bounded acquisition downloaded 6,970,018 compressed bytes from the 984,551,626-byte
CAIL2018 archive and produced a verified 24,702,198-byte validation JSONL member. A theft dry run scanned
17,131 records and found 991 unique eligible cases. The expanded plan selected 750 discovery and 200
held-out evaluation cases, estimated 32 future model calls, 575,424 input tokens, and a conservative
1,000,000-token output reserve. Its estimated total is 1,575,424 of the persistent 100,000,000-token
ceiling. It remains `execution_ready=false` solely because the dataset license review is pending; dry
planning did not reserve tokens and no model was called.

Three newer evaluation assets are also present locally under ignored storage with commit-pinned source
manifests: 300 CAIL2022-LCR queries (351,261 bytes), 800 LeCaRDv2 full-context queries (17,066,722
bytes), and 1,543 STARD consultation queries (1,818,895 bytes). Their combined size is 19,236,878 bytes.
They remain limited to research planning while license review is pending and are not yet accepted by
the factor-discovery loader or sent to a model.

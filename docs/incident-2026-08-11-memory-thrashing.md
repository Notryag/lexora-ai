# 2026-08-11 Full-Corpus Retrieval Memory Thrashing

## Status

- Severity: host outage
- Incident time: 2026-08-11 16:58-17:26 CST
- Root cause: confirmed
- Permanent fix: implemented and verified

## Impact

At 17:00 the 3.3 GiB host entered sustained memory reclaim and swap thrashing. Swap usage rose
from less than 1 MiB to about 1.1 GiB, major faults reached about 235 per second, kernel reclaim
reached about 7,000 pages per second, and five tasks were blocked. System logging stopped at
17:00:07. The host did not recover until it was forcibly restarted at 17:26.

This was not a CPU saturation, disk saturation, PostgreSQL failure, kernel panic, or external
traffic incident. CPU remained about 77% idle and the disk was about 11% utilized at the final
sample.

## Trigger

A local acceptance test started overlapping legal-conversation requests. Each request produced the
raw user question plus several focused authority queries. Two requests remained active together
immediately before the host stopped responding.

The high-traffic Docker interface was traced to `lexora-ai-postgres-1`. The traffic was PostgreSQL
returning retrieval data to the local API process over `127.0.0.1:5434`, not API ingress from the
internet.

## Root Cause

`DatabaseLegalKnowledgePort.search()` called `list_effective_chunks()` for every retrieval query.
That repository method selected every effective statute chunk, including its complete embedding,
and converted every vector into Python objects before ranking. The ORM join also selected the full
`legal_sources.content` field, so the complete source statute was transferred repeatedly for each of
its chunks even though online ranking did not use that field.

The corpus contained:

- 4,062 statute chunks;
- 2,445 populated embeddings;
- 1,024 dimensions per embedding.

The turn-preparation tool then executed multiple independent searches with `asyncio.gather`. One
request could fan out to seven full-corpus loads, and concurrent requests multiplied the same work.

A controlled read-only reproduction of one search measured:

- 605,822,167 bytes received from the PostgreSQL container (about 578 MiB);
- 678,380 KiB peak Python RSS (about 663 MiB);
- 6.18 seconds elapsed.

This made the failure deterministic once several searches overlapped. The application attempted to
create a working set larger than physical memory and swap, then spent nearly all useful time paging.

## Engineering Assessment

This was a basic bounded-resource design failure, not an obscure production edge case.

The implementation violated three standard retrieval rules:

1. It materialized an unbounded corpus in the application process.
2. It transferred vectors across the database boundary before applying Top-K.
3. It multiplied that unbounded operation through query and request concurrency.

PostgreSQL and pgvector already provide distance ordering and `LIMIT`. Fetching every vector into
Python for online retrieval should have been rejected during design or code review. A corpus-scale
smoke test, a peak-RSS assertion, or inspection of the generated SQL would also have exposed it
before runtime acceptance testing.

Docker memory limits were absent and allowed this application defect to take down the whole host.
That is a containment gap, but it is not the primary cause: a memory limit may turn the same bug into
an API container OOM, while server-side bounded retrieval removes the pathological work.

## Implemented Remediation

The permanent fix now enforces all of the following:

- Vector distance and Top-K selection run inside PostgreSQL/pgvector.
- The lightweight retrieval query excludes both chunk embeddings and full source documents.
- Lexical retrieval may inspect bounded text metadata, but only a small union of lexical and vector
  candidates may be hydrated with embeddings.
- A turn executes only the raw question plus at most three focused authority queries.
- Authority-query concurrency is two per turn; shared database retrieval concurrency is four.
- The lightweight lexical corpus scan fails closed above 10,000 chunks. The test-only local vector
  fallback fails closed above 500 chunks, and callers cannot request Top-K above 50.
- API, PostgreSQL, and Web containers have memory, swap, and PID limits.
- Retrieval tests cover result quality and resource behavior against a corpus-scale database.

The Compose defaults on this 3.3 GiB host are 768 MiB for API, 512 MiB for PostgreSQL, and 256 MiB
for Web. Each container's combined memory-and-swap limit equals its memory limit, preventing a
container from driving host swap. These values remain deployment-overridable after capacity review.

## Verification

The same corpus-scale legal query was repeated after the fix and returned six results:

| Measurement | Before | After | Change |
|---|---:|---:|---:|
| PostgreSQL bytes returned | 605,822,167 | 2,964,773 | -99.5% |
| Python peak RSS | 678,380 KiB | 148,088 KiB | -78.2% |
| Search elapsed time | 6.18 s | 0.29 s | -95.3% |

The after-fix peak includes roughly 127 MiB of interpreter and imported-framework baseline, leaving
about 18 MiB of incremental process RSS for the measured retrieval. Unit tests additionally inspect
the generated lightweight SQL and fail if either bulk column is selected. PostgreSQL-path tests
require vector candidate selection before the bounded candidate set is hydrated.

## Non-Regression Invariants

These are architecture constraints, not optional optimizations:

1. No request path may return all persisted embeddings to Python.
2. Every vector query must apply a database-side candidate limit.
3. Every fan-out must have a documented maximum and bounded concurrency.
4. Two simultaneous legal turns must remain below the API container memory limit.
5. Container limits must protect the host even when an application regression occurs.

Any future change that intentionally violates one of these constraints requires a design review,
an explicit bounded data-size argument, and a measured peak-memory test.

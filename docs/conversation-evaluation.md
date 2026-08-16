# Core Conversation Evaluation

## Purpose

This evaluation exercises the user-visible conversation path end to end:

```text
HTTP request
  -> SSE text deltas and runtime events
  -> completed Agent Run
  -> assistant answer and citation presentation
  -> CaseFactorProfile projection
  -> durable human/assistant message events
```

It is a product regression suite, not a legal benchmark and not a production rule engine. Scenario
terms and forbidden repeated questions live only under `evaluation/`; they do not influence Agent
routing, factor extraction, retrieval, or answers.

## Bounded Scenarios

The versioned suite contains five scenarios and six total user turns:

- a social greeting that must remain short and skip legal retrieval;
- an employment termination question that should distinguish compensation from unlawful-dismissal
  damages and use facts already supplied by the user;
- a two-turn theft sentencing question that must retain supplied facts and stop repeating them;
- a divorce-property question that should answer from known acquisition, registration, and loan facts;
- a marriage-overlap question that must not ask again whether the parties held themselves out as
  spouses.

Automated assertions cover response length, question count, required answer concepts, repeated or
irrelevant prompts, citation counts, delta count, streamed/final text equality, message ordering,
one human plus one assistant message per Run, latest Run completion, and prohibited factor-state
expansions in the persisted case profile. Multi-turn scenarios can also require factual supplements
to appear in durable `case_profile.key_facts`, which catches answers that use a new fact without
actually remembering it. The employment scenario asserts the exact N and 2N amounts rather than
accepting a merely plausible explanation. Each turn also includes a manual review rubric because
legal usefulness cannot be reduced to keyword assertions.

## Cost And Safety

The command is a dry-run unless `--execute` is present. Dry-run performs no HTTP request and no model
call.

```bash
uv run lexora-conversation-eval
```

Live execution is explicitly bounded by selected scenarios and user turns:

```bash
uv run lexora-conversation-eval \
  --execute \
  --scenario social_greeting \
  --scenario marriage_overlap \
  --output storage/evaluation/conversation-latest.json
```

The default live suite allows at most five scenarios. Each evaluation case receives a unique
`[conversation-eval:...]` title and is deleted by its returned case ID in a `finally` block. Use
`--keep-cases` only when the cases are intentionally needed for UI review.

North may perform multiple internal model calls for a single user turn because tool calls and the
follow-up reviewer are part of the Agent loop. The current public runtime and Run/event contract does
not expose those model-call or token-usage totals, so the report records both as `null` instead of
estimating them. This command is independent from factor discovery and does not read, consume, or
reset its cumulative 100M-token ledger.

## Interpreting Results

A passing automated report establishes transport and persistence consistency plus the narrow
scenario assertions. It does not establish legal correctness. Review the saved final answers,
citations, case profile, extracted follow-up questions, time to first delta, total duration, and each
turn's manual rubric before accepting a behavior change.

The report exits with status 1 when an automated assertion fails. A failed assertion should first be
classified as a product defect, an unstable model behavior, or an evaluation-fixture defect. Do not
respond by adding scenario keywords to production code.

Provider connection failures, timeouts, rate limits, and 5xx responses are reported separately under
`infrastructure_failures`. When any selected scenario does not reach an answer for that reason,
`quality_passed` is `null`: the run is unsuccessful, but the report does not pretend to have measured
answer quality. Bounded evaluation does not add an outer retry loop on top of the provider SDK's own
retry behavior.

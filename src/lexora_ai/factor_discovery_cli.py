from __future__ import annotations

import argparse
import json
from pathlib import Path

from lexora_ai.application.factor_discovery import build_factor_discovery_plan
from lexora_ai.domain.factor_discovery import FactorDiscoveryBudget
from lexora_ai.infrastructure.factor_discovery_ledger import FactorDiscoveryTokenLedger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan bounded offline factor discovery")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--format", choices=("cail2018", "synthetic"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--sha256",
        help="previously verified dataset SHA-256; the planner records but does not recompute it",
    )
    parser.add_argument("--issue", required=True)
    parser.add_argument("--model", default="unconfigured")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--discovery-cases", type=int, default=750)
    parser.add_argument("--evaluation-cases", type=int, default=200)
    parser.add_argument("--max-unique-cases", type=int, default=950)
    parser.add_argument("--max-model-calls", type=int, default=100)
    parser.add_argument("--max-input-tokens", type=int, default=10_000_000)
    parser.add_argument("--max-output-tokens", type=int, default=1_000_000)
    parser.add_argument("--max-batch-input-tokens", type=int, default=20_000)
    parser.add_argument("--max-records-scanned", type=int, default=50_000)
    parser.add_argument("--candidate-pool-multiplier", type=int, default=4)
    parser.add_argument("--max-case-chars", type=int, default=6_000)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--token-ledger",
        type=Path,
        default=Path("storage/factor-discovery/token-budget.sqlite3"),
        help="persistent cumulative token ledger; the 100M limit is not reset per run",
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help="acquisition manifest; defaults to <dataset>.source.json when present",
    )
    return parser


def _license_review_status(dataset: Path, source_manifest: Path | None) -> str:
    manifest = source_manifest or dataset.with_suffix(f"{dataset.suffix}.source.json")
    if not manifest.exists():
        return "unrecorded"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    status = payload.get("license_review_status")
    return status if isinstance(status, str) and status else "unrecorded"


def run() -> None:
    args = _parser().parse_args()
    token_ledger = FactorDiscoveryTokenLedger(args.token_ledger)
    budget = FactorDiscoveryBudget(
        discovery_cases=args.discovery_cases,
        evaluation_cases=args.evaluation_cases,
        max_unique_cases=args.max_unique_cases,
        max_model_calls=args.max_model_calls,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        max_batch_input_tokens=args.max_batch_input_tokens,
        max_records_scanned=args.max_records_scanned,
        candidate_pool_multiplier=args.candidate_pool_multiplier,
        max_case_chars=args.max_case_chars,
    )
    plan = build_factor_discovery_plan(
        args.dataset,
        dataset_format=args.format,
        dataset_name=args.name,
        dataset_version=args.version,
        dataset_sha256=args.sha256,
        license_review_status=_license_review_status(args.dataset, args.source_manifest),
        issue=args.issue,
        sampling_seed=args.seed,
        model=args.model,
        budget=budget,
        cumulative_token_budget=token_ledger.snapshot(),
    )
    rendered = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    if not plan.within_budget:
        raise SystemExit(2)

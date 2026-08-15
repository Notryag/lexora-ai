from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from lexora_ai.evaluation.conversation_e2e import (
    DEFAULT_SCENARIOS_PATH,
    build_plan,
    execute_suite,
    load_suite,
    select_scenarios,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or execute the bounded Lexora conversation evaluation"
    )
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS_PATH)
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="scenario ID to run; may be repeated (default: all)",
    )
    parser.add_argument("--max-scenarios", type=int, default=5)
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="send live requests; without this flag only the bounded plan is printed",
    )
    parser.add_argument(
        "--keep-cases",
        action="store_true",
        help="retain evaluation cases for manual UI review instead of deleting them",
    )
    parser.add_argument("--output", type=Path)
    return parser


def run() -> None:
    args = _parser().parse_args()
    if args.keep_cases and not args.execute:
        raise ValueError("--keep-cases requires --execute")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    suite = load_suite(args.scenarios)
    scenarios = select_scenarios(
        suite,
        args.scenario,
        max_scenarios=args.max_scenarios,
    )
    report = (
        asyncio.run(
            execute_suite(
                scenarios,
                base_url=args.base_url,
                timeout_seconds=args.timeout_seconds,
                keep_cases=args.keep_cases,
            )
        )
        if args.execute
        else build_plan(scenarios, base_url=args.base_url)
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    if args.execute and not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    run()

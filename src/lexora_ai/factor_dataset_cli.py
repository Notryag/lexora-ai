from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from lexora_ai.infrastructure.bounded_remote_zip import (
    BoundedRemoteZipMemberConnector,
    RemoteZipMemberSpec,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Acquire a bounded factor-discovery dataset member")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--dataset", default="cail2018")
    parser.add_argument("--member", default="validation-sample-pool")
    return parser


def _load_spec(dataset_name: str, member_name: str) -> tuple[dict[str, object], RemoteZipMemberSpec]:
    resource = files("lexora_ai.resources").joinpath("factor_discovery_datasets.json")
    datasets = json.loads(resource.read_text(encoding="utf-8"))
    dataset = next(
        (item for item in datasets if item.get("name") == dataset_name),
        None,
    )
    if dataset is None:
        raise ValueError(f"unknown factor discovery dataset: {dataset_name}")
    if dataset.get("acquisition_status") != "not_downloaded":
        raise ValueError("dataset source manifest has an unexpected acquisition status")
    if "research_planning" not in dataset.get("permitted_scopes", []):
        raise ValueError("dataset source is not approved for research planning acquisition")
    member = next(
        (item for item in dataset.get("members", []) if item.get("name") == member_name),
        None,
    )
    if member is None:
        raise ValueError(f"unknown dataset member: {member_name}")
    spec = RemoteZipMemberSpec(
        source_url=str(dataset["source_url"]),
        allowed_hostname=str(dataset["allowed_hostname"]),
        archive_size_bytes=int(dataset["archive_size_bytes"]),
        source_etag=str(dataset["source_etag"]),
        member_path=str(member["path"]),
        local_header_offset=int(member["local_header_offset"]),
        compression_method=int(member["compression_method"]),
        crc32=int(str(member["crc32"]), 16),
        compressed_size=int(member["compressed_size"]),
        uncompressed_size=int(member["uncompressed_size"]),
    )
    return dataset, spec


def run() -> None:
    args = _parser().parse_args()
    dataset, spec = _load_spec(args.dataset, args.member)
    result = BoundedRemoteZipMemberConnector().acquire(spec, args.destination)
    manifest = {
        "dataset": dataset["name"],
        "version": dataset["version"],
        "publisher": dataset["publisher"],
        "source_url": dataset["source_url"],
        "source_etag": dataset["source_etag"],
        "member": args.member,
        "member_path": spec.member_path,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "license_review_status": dataset["license_review_status"],
        "permitted_scopes": dataset["permitted_scopes"],
        **asdict(result),
    }
    manifest_path = args.destination.with_suffix(f"{args.destination.suffix}.source.json")
    manifest_path.write_text(
        f"{json.dumps(manifest, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {**manifest, "manifest": str(manifest_path)},
            ensure_ascii=False,
            indent=2,
        )
    )

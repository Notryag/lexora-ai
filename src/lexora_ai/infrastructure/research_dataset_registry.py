from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class ResearchDatasetFile:
    name: str
    purposes: tuple[str, ...]
    path: str
    source_url: str
    allowed_hostname: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ResearchDatasetRegistration:
    name: str
    version: str
    license_review_status: str
    permitted_scopes: tuple[str, ...]
    files: tuple[ResearchDatasetFile, ...]

    def file_for(self, *purposes: str) -> ResearchDatasetFile:
        matches = [source for source in self.files if set(source.purposes).intersection(purposes)]
        if len(matches) != 1:
            joined = ", ".join(purposes)
            raise ValueError(f"dataset must register exactly one file for {joined}: {self.name}")
        return matches[0]


def registered_research_datasets() -> dict[str, ResearchDatasetRegistration]:
    resource = files("lexora_ai.resources").joinpath("factor_discovery_datasets.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    registrations: dict[str, ResearchDatasetRegistration] = {}
    for dataset in payload:
        name = dataset.get("name")
        if name not in {"cail2022-lcr", "lecardv2", "stard"}:
            continue
        raw_scopes = dataset.get("permitted_scopes")
        if not isinstance(raw_scopes, list) or not all(
            isinstance(scope, str) for scope in raw_scopes
        ):
            raise ValueError(f"dataset permitted scopes are invalid: {name}")
        raw_files = dataset.get("files")
        if not isinstance(raw_files, list):
            raise ValueError(f"dataset files are invalid: {name}")
        registrations[str(name)] = ResearchDatasetRegistration(
            name=str(name),
            version=str(dataset["version"]),
            license_review_status=str(dataset.get("license_review_status", "unrecorded")),
            permitted_scopes=tuple(raw_scopes),
            files=tuple(_dataset_file(item, str(name)) for item in raw_files),
        )
    return registrations


def _dataset_file(payload: object, dataset_name: str) -> ResearchDatasetFile:
    if not isinstance(payload, dict):
        raise ValueError(f"dataset file is invalid: {dataset_name}")
    required_strings = (
        "name",
        "path",
        "source_url",
        "allowed_hostname",
        "sha256",
    )
    if any(not isinstance(payload.get(key), str) for key in required_strings):
        raise ValueError(f"dataset file registration is incomplete: {dataset_name}")
    raw_purposes = payload.get("purposes")
    if (
        not isinstance(raw_purposes, list)
        or not raw_purposes
        or not all(isinstance(purpose, str) and purpose for purpose in raw_purposes)
    ):
        raise ValueError(f"dataset file purposes are invalid: {dataset_name}")
    size = payload.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError(f"dataset file size is invalid: {dataset_name}")
    return ResearchDatasetFile(
        name=payload["name"],
        purposes=tuple(dict.fromkeys(raw_purposes)),
        path=payload["path"],
        source_url=payload["source_url"],
        allowed_hostname=payload["allowed_hostname"],
        size_bytes=size,
        sha256=payload["sha256"],
    )

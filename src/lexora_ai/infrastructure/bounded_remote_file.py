from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


class RemoteFileAcquisitionError(ValueError):
    pass


class _Response(Protocol):
    headers: object

    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> None: ...

    def geturl(self) -> str: ...

    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class RemoteFileSpec:
    source_url: str
    allowed_hostname: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AcquiredRemoteFile:
    destination: str
    sha256: str
    size_bytes: int
    downloaded_bytes: int
    outcome: str


class BoundedRemoteFileConnector:
    def __init__(
        self,
        *,
        max_download_bytes: int = 32 * 1024 * 1024,
        opener: Callable[..., _Response] = urlopen,
    ) -> None:
        self._max_download_bytes = max_download_bytes
        self._opener = opener

    def acquire(self, spec: RemoteFileSpec, destination: Path) -> AcquiredRemoteFile:
        self._validate_spec(spec)
        if destination.exists():
            digest, size = _file_digest(destination)
            if size != spec.size_bytes or digest != spec.sha256:
                raise RemoteFileAcquisitionError(
                    "existing destination does not match the expected remote file"
                )
            return _result(destination, digest, size, downloaded_bytes=0, outcome="unchanged")

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.part.{uuid4().hex}")
        request = Request(
            spec.source_url,
            headers={"User-Agent": "Lexora/0.1 bounded-dataset-acquisition"},
        )
        digest = sha256()
        size = 0
        try:
            with self._opener(request, timeout=60) as response:
                self._validate_final_url(spec, response.geturl())
                with temporary.open("xb") as output:
                    while chunk := response.read(64 * 1024):
                        size += len(chunk)
                        if size > spec.size_bytes or size > self._max_download_bytes:
                            raise RemoteFileAcquisitionError(
                                "remote file exceeded its bounded download size"
                            )
                        digest.update(chunk)
                        output.write(chunk)
            actual_digest = digest.hexdigest()
            if size != spec.size_bytes:
                raise RemoteFileAcquisitionError("remote file size changed from the source manifest")
            if actual_digest != spec.sha256:
                raise RemoteFileAcquisitionError("remote file SHA-256 changed from the source manifest")
            os.link(temporary, destination)
            temporary.unlink()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return _result(
            destination,
            actual_digest,
            size,
            downloaded_bytes=size,
            outcome="downloaded",
        )

    def _validate_spec(self, spec: RemoteFileSpec) -> None:
        parsed = urlparse(spec.source_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != spec.allowed_hostname:
            raise RemoteFileAcquisitionError("remote file is not on the allowed HTTPS host")
        if spec.size_bytes <= 0 or spec.size_bytes > self._max_download_bytes:
            raise RemoteFileAcquisitionError("remote file exceeds max_download_bytes")
        digest = spec.sha256.strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RemoteFileAcquisitionError("remote file SHA-256 manifest is invalid")

    @staticmethod
    def _validate_final_url(spec: RemoteFileSpec, final_url: str) -> None:
        parsed = urlparse(final_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != spec.allowed_hostname:
            raise RemoteFileAcquisitionError(
                "remote file redirected outside the allowed HTTPS host"
            )


def _file_digest(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _result(
    destination: Path,
    digest: str,
    size: int,
    *,
    downloaded_bytes: int,
    outcome: str,
) -> AcquiredRemoteFile:
    return AcquiredRemoteFile(
        destination=str(destination),
        sha256=digest,
        size_bytes=size,
        downloaded_bytes=downloaded_bytes,
        outcome=outcome,
    )

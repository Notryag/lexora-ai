from __future__ import annotations

import io
from dataclasses import replace
from email.message import Message
from hashlib import sha256
from pathlib import Path
from urllib.request import Request

import pytest

from lexora_ai.infrastructure.bounded_remote_file import (
    BoundedRemoteFileConnector,
    RemoteFileAcquisitionError,
    RemoteFileSpec,
)


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, *, url: str) -> None:
        super().__init__(payload)
        self._url = url
        self.headers = Message()

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _spec(payload: bytes) -> RemoteFileSpec:
    return RemoteFileSpec(
        source_url="https://raw.example.test/data.json",
        allowed_hostname="raw.example.test",
        size_bytes=len(payload),
        sha256=sha256(payload).hexdigest(),
    )


def _opener(payload: bytes):
    def open_request(request: Request, timeout: int):
        assert timeout > 0
        return FakeResponse(payload, url=request.full_url)

    return open_request


def test_connector_downloads_verified_file_once(tmp_path: Path) -> None:
    payload = b'{"case":"bounded"}\n'
    destination = tmp_path / "data.json"
    connector = BoundedRemoteFileConnector(opener=_opener(payload))

    downloaded = connector.acquire(_spec(payload), destination)
    unchanged = connector.acquire(_spec(payload), destination)

    assert destination.read_bytes() == payload
    assert downloaded.outcome == "downloaded"
    assert downloaded.downloaded_bytes == len(payload)
    assert unchanged.outcome == "unchanged"
    assert unchanged.downloaded_bytes == 0


def test_connector_rejects_content_that_changed_from_manifest(tmp_path: Path) -> None:
    expected = b"expected"
    connector = BoundedRemoteFileConnector(opener=_opener(b"changed!"))

    with pytest.raises(RemoteFileAcquisitionError, match="SHA-256"):
        connector.acquire(_spec(expected), tmp_path / "data.json")


def test_connector_rejects_redirect_outside_allowed_host(tmp_path: Path) -> None:
    payload = b"expected"
    unsafe = replace(_spec(payload), source_url="https://other.example.test/data.json")

    with pytest.raises(RemoteFileAcquisitionError, match="allowed HTTPS host"):
        BoundedRemoteFileConnector(opener=_opener(payload)).acquire(
            unsafe,
            tmp_path / "data.json",
        )

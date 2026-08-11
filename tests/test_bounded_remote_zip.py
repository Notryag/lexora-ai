from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from email.message import Message
from pathlib import Path
from urllib.request import Request

import pytest

from lexora_ai.infrastructure.bounded_remote_zip import (
    BoundedRemoteZipMemberConnector,
    RemoteZipAcquisitionError,
    RemoteZipMemberSpec,
)


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        status: int,
        url: str,
        headers: dict[str, str],
    ) -> None:
        super().__init__(payload)
        self.status = status
        self._url = url
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _archive() -> tuple[bytes, zipfile.ZipInfo]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dataset/sample.jsonl", '{"fact":"测试"}\n' * 20)
        info = archive.getinfo("dataset/sample.jsonl")
    return buffer.getvalue(), info


def _spec(data: bytes, info: zipfile.ZipInfo) -> RemoteZipMemberSpec:
    return RemoteZipMemberSpec(
        source_url="https://datasets.example.test/archive.zip",
        allowed_hostname="datasets.example.test",
        archive_size_bytes=len(data),
        source_etag="fixture-etag",
        member_path=info.filename,
        local_header_offset=info.header_offset,
        compression_method=info.compress_type,
        crc32=info.CRC,
        compressed_size=info.compress_size,
        uncompressed_size=info.file_size,
    )


def _opener(data: bytes, *, honor_range: bool = True):
    def open_request(request: Request, timeout: int):
        assert timeout > 0
        if request.get_method() == "HEAD":
            return FakeResponse(
                b"",
                status=200,
                url=request.full_url,
                headers={"Content-Length": str(len(data)), "ETag": '"fixture-etag"'},
            )
        range_header = request.get_header("Range")
        assert range_header is not None
        start_text, end_text = range_header.removeprefix("bytes=").split("-", maxsplit=1)
        start, end = int(start_text), int(end_text)
        if not honor_range:
            return FakeResponse(
                data,
                status=200,
                url=request.full_url,
                headers={"Content-Length": str(len(data))},
            )
        return FakeResponse(
            data[start : end + 1],
            status=206,
            url=request.full_url,
            headers={
                "Content-Length": str(end - start + 1),
                "Content-Range": f"bytes {start}-{end}/{len(data)}",
            },
        )

    return open_request


def test_connector_downloads_only_manifest_member_and_is_idempotent(tmp_path: Path) -> None:
    data, info = _archive()
    destination = tmp_path / "sample.jsonl"
    connector = BoundedRemoteZipMemberConnector(opener=_opener(data))

    downloaded = connector.acquire(_spec(data, info), destination)
    unchanged = connector.acquire(_spec(data, info), destination)

    assert destination.read_text(encoding="utf-8") == '{"fact":"测试"}\n' * 20
    assert downloaded.outcome == "downloaded"
    assert downloaded.downloaded_bytes == info.compress_size
    assert unchanged.outcome == "unchanged"
    assert unchanged.downloaded_bytes == 0
    assert unchanged.sha256 == downloaded.sha256


def test_connector_rejects_server_that_ignores_range(tmp_path: Path) -> None:
    data, info = _archive()
    connector = BoundedRemoteZipMemberConnector(opener=_opener(data, honor_range=False))

    with pytest.raises(RemoteZipAcquisitionError, match="did not honor"):
        connector.acquire(_spec(data, info), tmp_path / "sample.jsonl")


def test_connector_rejects_source_outside_allowlisted_host(tmp_path: Path) -> None:
    data, info = _archive()
    spec = _spec(data, info)
    unsafe = replace(spec, source_url="https://other.example.test/archive.zip")

    with pytest.raises(RemoteZipAcquisitionError, match="allowed HTTPS host"):
        BoundedRemoteZipMemberConnector(opener=_opener(data)).acquire(
            unsafe,
            tmp_path / "sample.jsonl",
        )

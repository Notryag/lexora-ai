from __future__ import annotations

import os
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


class RemoteZipAcquisitionError(ValueError):
    pass


class _Response(Protocol):
    status: int
    headers: object

    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> None: ...

    def geturl(self) -> str: ...

    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class RemoteZipMemberSpec:
    source_url: str
    allowed_hostname: str
    archive_size_bytes: int
    source_etag: str
    member_path: str
    local_header_offset: int
    compression_method: int
    crc32: int
    compressed_size: int
    uncompressed_size: int


@dataclass(frozen=True, slots=True)
class AcquiredZipMember:
    destination: str
    member_path: str
    sha256: str
    crc32: str
    size_bytes: int
    downloaded_bytes: int
    outcome: str


class BoundedRemoteZipMemberConnector:
    def __init__(
        self,
        *,
        max_download_bytes: int = 16 * 1024 * 1024,
        max_uncompressed_bytes: int = 64 * 1024 * 1024,
        opener: Callable[..., _Response] = urlopen,
    ) -> None:
        self._max_download_bytes = max_download_bytes
        self._max_uncompressed_bytes = max_uncompressed_bytes
        self._opener = opener

    def acquire(self, spec: RemoteZipMemberSpec, destination: Path) -> AcquiredZipMember:
        self._validate_spec(spec)
        self._validate_remote_archive(spec)
        if destination.exists():
            digest, crc, size = _file_digests(destination)
            if size != spec.uncompressed_size or crc != spec.crc32:
                raise RemoteZipAcquisitionError(
                    "existing destination does not match the expected ZIP member"
                )
            return AcquiredZipMember(
                destination=str(destination),
                member_path=spec.member_path,
                sha256=digest,
                crc32=f"{crc:08x}",
                size_bytes=size,
                downloaded_bytes=0,
                outcome="unchanged",
            )

        header = self._read_range(
            spec,
            spec.local_header_offset,
            spec.local_header_offset + 29,
        )
        data_offset = _validate_local_header(header, spec, self._read_range)
        compressed_end = data_offset + spec.compressed_size - 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.part.{uuid4().hex}")
        try:
            digest, crc, size = self._download_and_decompress(
                spec,
                start=data_offset,
                end=compressed_end,
                destination=temporary,
            )
            if size != spec.uncompressed_size:
                raise RemoteZipAcquisitionError("uncompressed member size does not match manifest")
            if crc != spec.crc32:
                raise RemoteZipAcquisitionError("uncompressed member CRC does not match manifest")
            os.link(temporary, destination)
            temporary.unlink()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return AcquiredZipMember(
            destination=str(destination),
            member_path=spec.member_path,
            sha256=digest,
            crc32=f"{crc:08x}",
            size_bytes=size,
            downloaded_bytes=spec.compressed_size,
            outcome="downloaded",
        )

    def _validate_spec(self, spec: RemoteZipMemberSpec) -> None:
        parsed = urlparse(spec.source_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != spec.allowed_hostname:
            raise RemoteZipAcquisitionError("remote ZIP source is not on the allowed HTTPS host")
        if spec.compression_method != 8:
            raise RemoteZipAcquisitionError("only deflated ZIP members are supported")
        if spec.compressed_size > self._max_download_bytes:
            raise RemoteZipAcquisitionError("compressed member exceeds max_download_bytes")
        if spec.uncompressed_size > self._max_uncompressed_bytes:
            raise RemoteZipAcquisitionError("member exceeds max_uncompressed_bytes")
        if spec.local_header_offset < 0 or spec.compressed_size <= 0 or spec.uncompressed_size <= 0:
            raise RemoteZipAcquisitionError("remote ZIP member manifest is invalid")

    def _validate_remote_archive(self, spec: RemoteZipMemberSpec) -> None:
        request = Request(
            spec.source_url,
            method="HEAD",
            headers={"User-Agent": "Lexora/0.1 bounded-dataset-acquisition"},
        )
        with self._opener(request, timeout=20) as response:
            self._validate_final_url(spec, response.geturl())
            length = _header(response.headers, "Content-Length")
            etag = _header(response.headers, "ETag").strip('"')
            if length != str(spec.archive_size_bytes):
                raise RemoteZipAcquisitionError("remote ZIP size changed from the source manifest")
            if etag != spec.source_etag.strip('"'):
                raise RemoteZipAcquisitionError("remote ZIP ETag changed from the source manifest")

    def _read_range(self, spec: RemoteZipMemberSpec, start: int, end: int) -> bytes:
        expected_size = end - start + 1
        request = Request(
            spec.source_url,
            headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "Lexora/0.1 bounded-dataset-acquisition",
            },
        )
        with self._opener(request, timeout=30) as response:
            self._validate_range_response(spec, response, start, end)
            payload = response.read(expected_size + 1)
        if len(payload) != expected_size:
            raise RemoteZipAcquisitionError("remote ZIP range returned an unexpected byte count")
        return payload

    def _download_and_decompress(
        self,
        spec: RemoteZipMemberSpec,
        *,
        start: int,
        end: int,
        destination: Path,
    ) -> tuple[str, int, int]:
        request = Request(
            spec.source_url,
            headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "Lexora/0.1 bounded-dataset-acquisition",
            },
        )
        digest = sha256()
        crc = 0
        size = 0
        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        with self._opener(request, timeout=60) as response:
            self._validate_range_response(spec, response, start, end)
            with destination.open("xb") as output:
                compressed_read = 0
                while chunk := response.read(min(64 * 1024, spec.compressed_size - compressed_read)):
                    compressed_read += len(chunk)
                    if compressed_read > spec.compressed_size:
                        raise RemoteZipAcquisitionError("remote ZIP exceeded the bounded range")
                    data = decompressor.decompress(chunk)
                    if data:
                        size, crc = _write_checked(
                            output,
                            data,
                            digest=digest,
                            crc=crc,
                            size=size,
                            max_size=self._max_uncompressed_bytes,
                        )
                if compressed_read != spec.compressed_size:
                    raise RemoteZipAcquisitionError("remote ZIP member download was incomplete")
                trailing = decompressor.flush()
                if trailing:
                    size, crc = _write_checked(
                        output,
                        trailing,
                        digest=digest,
                        crc=crc,
                        size=size,
                        max_size=self._max_uncompressed_bytes,
                    )
        if not decompressor.eof:
            raise RemoteZipAcquisitionError("remote ZIP member deflate stream is incomplete")
        return digest.hexdigest(), crc & 0xFFFFFFFF, size

    def _validate_range_response(
        self,
        spec: RemoteZipMemberSpec,
        response: _Response,
        start: int,
        end: int,
    ) -> None:
        self._validate_final_url(spec, response.geturl())
        if response.status != 206:
            raise RemoteZipAcquisitionError("remote server did not honor the bounded Range request")
        expected = f"bytes {start}-{end}/{spec.archive_size_bytes}"
        if _header(response.headers, "Content-Range") != expected:
            raise RemoteZipAcquisitionError("remote ZIP returned an unexpected Content-Range")

    @staticmethod
    def _validate_final_url(spec: RemoteZipMemberSpec, final_url: str) -> None:
        parsed = urlparse(final_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != spec.allowed_hostname:
            raise RemoteZipAcquisitionError("remote ZIP redirected outside the allowed HTTPS host")


def _validate_local_header(
    header: bytes,
    spec: RemoteZipMemberSpec,
    read_range: Callable[[RemoteZipMemberSpec, int, int], bytes],
) -> int:
    if len(header) != 30:
        raise RemoteZipAcquisitionError("remote ZIP local header is incomplete")
    (
        signature,
        _version,
        flags,
        compression,
        _time,
        _date,
        crc,
        compressed_size,
        uncompressed_size,
        name_length,
        extra_length,
    ) = struct.unpack("<4s5H3L2H", header)
    if signature != b"PK\x03\x04":
        raise RemoteZipAcquisitionError("remote ZIP local header signature is invalid")
    if flags & 0x1:
        raise RemoteZipAcquisitionError("encrypted ZIP members are not supported")
    if flags & 0x8:
        raise RemoteZipAcquisitionError("ZIP data descriptors are not supported")
    if (
        compression != spec.compression_method
        or crc != spec.crc32
        or compressed_size != spec.compressed_size
        or uncompressed_size != spec.uncompressed_size
    ):
        raise RemoteZipAcquisitionError("remote ZIP local header changed from the source manifest")
    metadata_end = spec.local_header_offset + 30 + name_length + extra_length - 1
    metadata = read_range(spec, spec.local_header_offset + 30, metadata_end)
    member_name = metadata[:name_length].decode("utf-8")
    if member_name != spec.member_path:
        raise RemoteZipAcquisitionError("remote ZIP member path changed from the source manifest")
    return metadata_end + 1


def _write_checked(
    output: object,
    data: bytes,
    *,
    digest: object,
    crc: int,
    size: int,
    max_size: int,
) -> tuple[int, int]:
    next_size = size + len(data)
    if next_size > max_size:
        raise RemoteZipAcquisitionError("uncompressed member exceeded the configured limit")
    output.write(data)
    digest.update(data)
    return next_size, zlib.crc32(data, crc)


def _file_digests(path: Path) -> tuple[str, int, int]:
    digest = sha256()
    crc = 0
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            size += len(chunk)
            digest.update(chunk)
            crc = zlib.crc32(chunk, crc)
    return digest.hexdigest(), crc & 0xFFFFFFFF, size


def _header(headers: object, name: str) -> str:
    value = headers.get(name)
    if not isinstance(value, str):
        raise RemoteZipAcquisitionError(f"remote ZIP response has no {name} header")
    return value
